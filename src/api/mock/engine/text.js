const STOPWORDS = new Set(
  `a an the and or but if then so to of in on at for from by with about as is are was were be been being am
   i im me my we our us you your it its this that these those do does did doing have has had can could would
   should will just not no yes hi hello hey please there here what which who whom into up out over any some
   also really very get got still one thing ive dont didnt cant wont hasnt isnt yet now`.split(/\s+/),
);

// Deliberately crude suffix stripping — enough to match "shipped" with "shipping" and "damaged" with "damage".
export function stem(word) {
  let w = word;
  if (w.length > 5 && w.endsWith('ing')) w = w.slice(0, -3);
  else if (w.length > 4 && w.endsWith('ed')) w = w.slice(0, -2);
  else if (w.length > 4 && w.endsWith('es')) w = w.slice(0, -2);
  else if (w.length > 3 && w.endsWith('s') && !w.endsWith('ss')) w = w.slice(0, -1);

  if (w.length > 4 && w.endsWith('e')) w = w.slice(0, -1);
  if (w.length > 3 && /([bcdfgklmnprt])\1$/.test(w)) w = w.slice(0, -1);
  return w;
}

export function tokenize(text) {
  return (text.toLowerCase().replace(/['’]/g, '').match(/[a-z0-9]+/g) ?? [])
    .filter((token) => token.length > 1 && !STOPWORDS.has(token))
    .map(stem);
}

export const round2 = (n) => Math.round(n * 100) / 100;

export const truncate = (text, max = 80) => (text.length > max ? `${text.slice(0, max - 1).trimEnd()}…` : text);
