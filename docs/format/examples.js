import { renderFormat2Previews } from "../js/skin2/catalog-preview.js";

for (const figure of document.querySelectorAll("[data-skin-example]")) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Render preview";
  figure.append(button);
  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Rendering…";
    try {
      const response = await fetch(figure.dataset.skinExample);
      if (!response.ok) throw new Error("Could not load the example");
      const previews = await renderFormat2Previews(await response.text());
      const orientation = document.createElement("select");
      orientation.setAttribute("aria-label", "Preview orientation");
      for (const value of previews.keys()) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value[0].toUpperCase() + value.slice(1);
        orientation.append(option);
      }
      const output = document.createElement("div");
      const show = () => {
        const canvas = previews.get(orientation.value);
        canvas.setAttribute("role", "img");
        canvas.setAttribute("aria-label", orientation.value + " skin layout");
        output.replaceChildren(canvas);
      };
      orientation.addEventListener("change", show);
      button.replaceWith(orientation, output);
      show();
    } catch (error) {
      button.disabled = false;
      button.textContent = "Retry preview";
      const status = figure.querySelector("[role=status]") ?? document.createElement("p");
      status.setAttribute("role", "status");
      status.textContent = error.message;
      figure.append(status);
    }
  });
}
