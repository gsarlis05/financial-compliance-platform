"""Platform users. A user is global (one person may belong to several workspaces); everything a
user may see is resolved through tenancy memberships (docs/planning/03 §1, 11 §2).

Passwords are never stored: authentication is delegated to the OIDC identity provider.
"""

from typing import ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models

from fcp.core.ids import uuid7


class UserManager(BaseUserManager["User"]):
    def get_or_create_from_oidc(
        self, *, subject: str, email: str, display_name: str
    ) -> tuple["User", bool]:
        user, created = self.get_or_create(
            idp_subject=subject, defaults={"email": email, "display_name": display_name}
        )
        changed = []
        if user.email != email:
            user.email = email
            changed.append("email")
        if display_name and user.display_name != display_name:
            user.display_name = display_name
            changed.append("display_name")
        if changed:
            user.save(update_fields=changed)
        return user, created


class User(AbstractBaseUser):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        DISABLED = "DISABLED"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    # Issuer-qualified subject ("<issuer>|<sub>"), unique per identity provider.
    idp_subject = models.CharField(max_length=512, unique=True)
    email = models.EmailField(max_length=320)
    display_name = models.CharField(max_length=200, blank=True)
    locale = models.CharField(max_length=10, default="en")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)

    # Django requires a password column on AbstractBaseUser; it is always unusable.
    USERNAME_FIELD = "idp_subject"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = ["email"]

    objects = UserManager()

    class Meta:
        db_table = "identity_user"

    def save(self, *args: object, **kwargs: object) -> None:
        if not self.password:
            self.set_unusable_password()
        super().save(*args, **kwargs)  # type: ignore[arg-type]

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        return self.status == self.Status.ACTIVE

    def __str__(self) -> str:
        return str(self.id)
