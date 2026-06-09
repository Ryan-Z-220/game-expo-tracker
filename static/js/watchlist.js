document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector(".watchlist-toggle-form");

  if (!form) {
    return;
  }

  const button = form.querySelector("button");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const isInWatchlist = form.dataset.inWatchlist === "true";
    const targetUrl = isInWatchlist
      ? form.dataset.removeUrl
      : form.dataset.addUrl;

    button.disabled = true;
    const originalText = button.textContent;
    button.textContent = "Updating...";

    try {
      const formData = new FormData(form);

      const response = await fetch(targetUrl, {
        method: "POST",
        body: formData,
        headers: {
          "X-Requested-With": "fetch",
        },
      });

      const result = await response.json();

      if (!response.ok || !result.success) {
        throw new Error(result.message || "Watchlist update failed.");
      }

      const nowInWatchlist = result.in_watchlist === true;

      form.dataset.inWatchlist = nowInWatchlist ? "true" : "false";
      form.action = nowInWatchlist
        ? form.dataset.removeUrl
        : form.dataset.addUrl;

      if (nowInWatchlist) {
        button.textContent = "Remove from Watchlist";
        button.classList.add("danger-button");
      } else {
        button.textContent = "Add to Watchlist";
        button.classList.remove("danger-button");
      }
    } catch (error) {
      alert(error.message);
      button.textContent = originalText;
    } finally {
      button.disabled = false;
    }
  });
});