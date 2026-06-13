document.addEventListener("DOMContentLoaded", () => {
  const menu = document.querySelector(".account-menu");
  const button = document.querySelector(".account-button");

  if (!menu || !button) {
    return;
  }

  button.addEventListener("click", (event) => {
    event.stopPropagation();

    const isOpen = menu.classList.toggle("open");
    button.setAttribute("aria-expanded", isOpen ? "true" : "false");
  });

  document.addEventListener("click", () => {
    menu.classList.remove("open");
    button.setAttribute("aria-expanded", "false");
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      menu.classList.remove("open");
      button.setAttribute("aria-expanded", "false");
    }
  });
});