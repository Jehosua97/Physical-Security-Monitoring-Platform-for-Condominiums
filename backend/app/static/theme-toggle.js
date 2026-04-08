(function bootstrapThemeToggle() {
  const STORAGE_KEY = "monitoring-ui-theme";

  function getSavedTheme() {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return saved === "dark" || saved === "light" ? saved : "light";
  }

  function nextTheme(theme) {
    return theme === "dark" ? "light" : "dark";
  }

  function buttonLabel(theme) {
    return theme === "dark" ? "Cambiar a claro" : "Cambiar a oscuro";
  }

  function applyTheme(theme) {
    document.body.dataset.theme = theme;
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.textContent = buttonLabel(theme);
      button.setAttribute("aria-label", buttonLabel(theme));
      button.dataset.nextTheme = nextTheme(theme);
    });
  }

  window.addEventListener("DOMContentLoaded", () => {
    applyTheme(getSavedTheme());

    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        const theme = document.body.dataset.theme || "light";
        const targetTheme = nextTheme(theme);
        window.localStorage.setItem(STORAGE_KEY, targetTheme);
        applyTheme(targetTheme);
      });
    });
  });
})();
