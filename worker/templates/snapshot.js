() => {
  const SEL = 'a[href], button, input, select, textarea, [role="button"]';
  const els = Array.from(document.querySelectorAll(SEL));
  const out = [];
  let i = 1;
  for (const el of els) {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) continue;
    const tag = el.tagName.toLowerCase();
    let role = el.getAttribute('role') || '';
    if (!role) {
      if (tag === 'a') role = 'link';
      else if (tag === 'button') role = 'button';
      else if (tag === 'select') role = 'select';
      else if (tag === 'textarea') role = 'textbox';
      else if (tag === 'input') {
        const t = (el.getAttribute('type') || 'text').toLowerCase();
        role = (t === 'submit' || t === 'button') ? 'button' : (t === 'checkbox' ? 'checkbox' : 'textbox');
      } else role = tag;
    }
    let label = '';
    if (el.labels && el.labels.length) {
      const clone = el.labels[0].cloneNode(true);
      clone.querySelectorAll('input, select, textarea, button').forEach(n => n.remove());
      label = clone.innerText || clone.textContent || '';
    }
    if (!label) label = el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.innerText || el.value || '';
    label = (label || '').trim().replace(/\s+/g, ' ').slice(0, 80);
    let value = '';
    if (tag === 'input' || tag === 'textarea') value = el.value || '';
    if (tag === 'select') {
      const opt = el.options[el.selectedIndex];
      value = opt ? opt.text : '';
    }
    el.setAttribute('data-agent-id', String(i));
    out.push({
      id: i, role, label, value,
      disabled: !!el.disabled,
      risk: el.getAttribute('data-risk') || '',
    });
    i++;
  }
  const text = document.body.innerText.trim().replace(/\n{3,}/g, '\n\n').slice(0, 4000);
  return {url: location.href, text, elements: out};
}
