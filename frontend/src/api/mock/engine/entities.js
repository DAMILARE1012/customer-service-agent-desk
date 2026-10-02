const PATTERNS = [
  {
    type: 'order_id',
    label: 'Order',
    regex: /(?:order\s*(?:number|no\.?)?\s*#?\s*|#)(\d{4,})/gi,
    format: (match) => `#${match[1]}`,
  },
  {
    type: 'email',
    label: 'Email',
    regex: /[\w.+-]+@[\w-]+\.[\w.]+/g,
    format: (match) => match[0],
  },
  {
    type: 'amount',
    label: 'Amount',
    regex: /\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?/g,
    format: (match) => match[0].replace(/\s/g, ''),
  },
  {
    type: 'promo_code',
    label: 'Promo code',
    regex: /\b[A-Z]{3,}\d{1,3}\b/g,
    format: (match) => match[0],
  },
];

export function extractEntities(text, messageId) {
  return PATTERNS.flatMap(({ type, label, regex, format }) =>
    [...text.matchAll(regex)].map((match) => ({ type, label, value: format(match), messageId })),
  );
}

export function mergeEntities(existing, incoming) {
  const seen = new Set(existing.map((e) => `${e.type}:${e.value}`));
  const merged = [...existing];
  for (const entity of incoming) {
    const key = `${entity.type}:${entity.value}`;
    if (!seen.has(key)) {
      seen.add(key);
      merged.push(entity);
    }
  }
  return merged;
}
