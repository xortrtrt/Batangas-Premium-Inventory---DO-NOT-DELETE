function updateSupplyForm(form) {
  const select = form.querySelector('[data-supply-unit]');
  const quantity = form.querySelector('[data-supply-quantity]');
  if (!select || !quantity) return;
  const choice = select.selectedOptions[0];
  const unit = select.name === 'unit' ? select.value : choice?.dataset.unit || '';
  const meters = unit === 'meter';
  quantity.step = meters ? '0.001' : '1';
  quantity.min = quantity.name === 'initial_quantity' ? '0' : meters ? '0.001' : '1';
  quantity.max = meters ? '999999999.999' : '999999999';
  const help = form.querySelector('[data-supply-unit-help]');
  const unitLabels = { piece: 'pieces', pair: 'pairs', box: 'boxes', roll: 'rolls', pack: 'packs', meter: 'meters' };
  if (help) help.textContent = unit ? `(${unitLabels[unit] || unit})` : '';
  const preview = form.querySelector('[data-supply-selected-image]');
  if (preview) {
    preview.src = choice?.dataset.image || '/static/img/supplies-stockroom.svg';
    preview.alt = choice?.dataset.name || 'Supply preview';
    form.querySelector('[data-supply-selected-name]').textContent = choice?.dataset.name || 'Choose a supply item';
    form.querySelector('[data-supply-selected-balance]').textContent = unit ? `${choice.dataset.balance} ${unit} available` : 'Select an item to view its balance.';
  }
}

function initializeSupplyForms(root = document) {
  if (root.matches?.('[data-supply-form]')) updateSupplyForm(root);
  root.querySelectorAll('[data-supply-form]').forEach(updateSupplyForm);
}

// Use the fields' native constraints with inline feedback, including forms
// introduced by entry-page navigation. The server remains authoritative.
document.addEventListener('submit', (event) => {
  const form = event.target;
  if (!form.matches?.('.supplies-workspace form')) return;
  if (form.dataset.submitting === 'true') {
    event.preventDefault();
    event.stopImmediatePropagation();
    return;
  }
  form.dataset.validationId ||= crypto.randomUUID();
  let firstInvalid;
  Array.from(form.elements).forEach((field, index) => {
    if (!field.willValidate) return;
    const id = `supply-error-${form.dataset.validationId}-${index}`;
    let error = form.querySelector(`#${id}`);
    if (!field.validity.valid) {
      if (!error) {
        error = document.createElement('span');
        error.id = id;
        error.className = 'supplies-field-error';
        field.insertAdjacentElement('afterend', error);
      }
      error.textContent = field.validationMessage;
      field.setAttribute('aria-invalid', 'true');
      const descriptions = new Set((field.getAttribute('aria-describedby') || '').split(' ').filter(Boolean));
      descriptions.add(id);
      field.setAttribute('aria-describedby', Array.from(descriptions).join(' '));
      firstInvalid ||= field;
    } else if (error) {
      error.remove();
      field.removeAttribute('aria-invalid');
      const descriptions = (field.getAttribute('aria-describedby') || '').split(' ').filter(value => value && value !== id);
      if (descriptions.length) field.setAttribute('aria-describedby', descriptions.join(' '));
      else field.removeAttribute('aria-describedby');
    }
  });
  if (firstInvalid) {
    event.preventDefault();
    event.stopImmediatePropagation();
    firstInvalid.focus();
  } else if (form.method.toLowerCase() === 'post') {
    form.dataset.submitting = 'true';
    form.setAttribute('aria-busy', 'true');
  }
}, true);

// Tab/filter navigation replaces the form nodes. Delegate selection events to
// the document so new forms work without reattaching listeners to each select.
document.addEventListener('change', (event) => {
  if (!event.target.matches?.('[data-supply-unit]')) return;
  const form = event.target.closest('[data-supply-form]');
  if (form) updateSupplyForm(form);
});
document.addEventListener('portal:content-updated', (event) => initializeSupplyForms(event.detail?.root || document));
window.addEventListener('pageshow', () => {
  document.querySelectorAll('.supplies-workspace form[data-submitting]').forEach(form => {
    if (!form.dataset?.submitting) return;
    delete form.dataset.submitting;
    form.removeAttribute('aria-busy');
  });
  initializeSupplyForms();
});
initializeSupplyForms();
