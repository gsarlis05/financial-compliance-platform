import "@testing-library/jest-dom/vitest";

// jsdom does not implement layout APIs; pages may scroll panels into view.
Element.prototype.scrollIntoView = () => undefined;
