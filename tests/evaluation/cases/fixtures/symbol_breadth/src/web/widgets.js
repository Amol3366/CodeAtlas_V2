export function renderOrder(view) {
  return `<li>${view.id}</li>`;
}

export const renderList = (views) => views.map(renderOrder).join("");

export default function mount(node, views) {
  node.innerHTML = renderList(views);
}
