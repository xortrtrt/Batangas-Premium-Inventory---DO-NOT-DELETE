(() => {
  document.querySelectorAll('[data-package-dispatch]').forEach((form) => {
    const customized = form.querySelector('[data-customized-contents]');
    const standardSummary = form.querySelector('[data-standard-dispatch]');
    const submit = form.querySelector('[data-package-dispatch-submit]');
    const label = form.querySelector('[data-package-dispatch-label]');
    const update = () => {
      const standard = form.querySelector('input[name="dispatch_mode"]:checked')?.value === 'standard';
      customized.hidden = standard;
      customized.disabled = standard;
      standardSummary.hidden = !standard;
      submit.disabled = standard && Number(form.dataset.standardCapacity) === 0;
      label.textContent = standard ? 'Dispatch standard package' : 'Dispatch customized package';
    };
    form.querySelectorAll('input[name="dispatch_mode"]').forEach((input) => input.addEventListener('change', update));
    update();
  });
})();
