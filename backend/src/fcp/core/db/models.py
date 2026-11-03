"""No models. This module exists so Django sends this app the post_migrate signal (Django skips
apps without a models module), which applies the runtime-role grants after every migration."""
