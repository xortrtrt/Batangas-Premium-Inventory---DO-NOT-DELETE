import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

function supplyForm(choice) {
  const listeners = new Map();
  const fields = {
    '[data-supply-quantity]': { name: 'quantity' },
    '[data-supply-unit-help]': {},
    '[data-supply-selected-image]': {},
    '[data-supply-selected-name]': {},
    '[data-supply-selected-balance]': {},
  };
  const form = {
    querySelector: (selector) => fields[selector],
    querySelectorAll: () => [],
    matches: (selector) => selector === '[data-supply-form]',
  };
  const select = {
    name: 'supply_id', selectedOptions: [choice],
    matches: (selector) => selector === '[data-supply-unit]',
    closest: () => form,
    addEventListener: (event, callback) => listeners.set(event, callback),
  };
  fields['[data-supply-unit]'] = select;
  return { form, select, fields, listeners };
}

test('selection previews and quantity units work after forms are replaced by tab navigation', () => {
  const original = supplyForm({ dataset: {} });
  let forms = [original.form];
  const documentListeners = new Map();
  const windowListeners = new Map();
  const document = {
    querySelectorAll: () => forms,
    addEventListener: (name, callback) => documentListeners.set(name, callback),
  };
  const window = { addEventListener: (name, callback) => windowListeners.set(name, callback) };
  runInNewContext(readFileSync(new URL('../app/static/js/supplies.js', import.meta.url), 'utf8'), { document, window });

  // This form did not exist when the module ran: it represents Stock Out
  // loaded by the portal's asynchronous tab navigation.
  const replacement = supplyForm({ dataset: {
    unit: 'piece', image: '/portal/inventory/supplies/42/image', name: 'Gloves', balance: '10',
  } });
  forms = [replacement.form];
  replacement.listeners.get('change')?.();
  documentListeners.get('change')?.({ target: replacement.select });
  assert.equal(replacement.fields['[data-supply-selected-image]'].src, '/portal/inventory/supplies/42/image');
  assert.equal(replacement.fields['[data-supply-selected-name]'].textContent, 'Gloves');
  assert.equal(replacement.fields['[data-supply-selected-balance]'].textContent, '10 piece available');
  assert.equal(replacement.fields['[data-supply-quantity]'].step, '1');
  assert.equal(replacement.fields['[data-supply-unit-help]'].textContent, '(pieces)');

  const restored = supplyForm({ dataset: { unit: 'meter', image: '/tape.png', name: 'Tape', balance: '2.5' } });
  forms = [restored.form];
  documentListeners.get('portal:content-updated')?.({ detail: { root: restored.form } });
  assert.equal(restored.fields['[data-supply-selected-image]'].src, '/tape.png');
  assert.equal(restored.fields['[data-supply-quantity]'].step, '0.001');
  assert.equal(restored.fields['[data-supply-quantity]'].min, '0.001');
  assert.equal(restored.fields['[data-supply-unit-help]'].textContent, '(meters)');

  restored.select.selectedOptions = [{ dataset: {} }];
  windowListeners.get('pageshow')?.();
  assert.equal(restored.fields['[data-supply-selected-name]'].textContent, 'Choose a supply item');
  assert.equal(restored.fields['[data-supply-selected-image]'].src, '/static/img/supplies-stockroom.svg');
  assert.equal(restored.fields['[data-supply-unit-help]'].textContent, '');
});
