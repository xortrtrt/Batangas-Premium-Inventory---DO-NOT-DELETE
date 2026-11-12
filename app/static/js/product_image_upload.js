const previewUrls = new WeakMap();
function clearPreview(container) {
  const previous = previewUrls.get(container);
  if (previous) URL.revokeObjectURL(previous);
  previewUrls.delete(container);
  const preview = container.querySelector('[data-product-image-preview]');
  preview.hidden = true;
  preview.removeAttribute('src');
  container.querySelector('[data-product-image-clear]').hidden = true;
}
document.addEventListener('change', (event) => {
  if (!event.target.matches('[data-product-image-input]')) return;
  const input = event.target;
  const container = input.closest('[data-product-image-upload]');
  clearPreview(container);
  const file = input.files[0];
  const status = container.querySelector('[data-product-image-status]');
  if (!file) { status.textContent = 'No image selected.'; return; }
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 2097152 || file.size === 0) {
    input.value = '';
    status.textContent = 'Choose a JPG, PNG, or WebP image up to 2 MB.';
    return;
  }
  const previewUrl = URL.createObjectURL(file);
  previewUrls.set(container, previewUrl);
  const preview = container.querySelector('[data-product-image-preview]');
  preview.src = previewUrl;
  preview.hidden = false;
  container.querySelector('[data-product-image-clear]').hidden = false;
  status.textContent = file.name;
});
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-product-image-clear]');
  if (!button) return;
  const container = button.closest('[data-product-image-upload]');
  container.querySelector('[data-product-image-input]').value = '';
  clearPreview(container);
  container.querySelector('[data-product-image-status]').textContent = 'No image selected.';
});
