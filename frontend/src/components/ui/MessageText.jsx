// The model answers in light Markdown. Render the two bits it uses — **bold** and "* " / "- " bullets —
// as React elements (never as HTML), and leave everything else as typed. Line breaks come from the
// bubble's whitespace style.
const BULLET = /^(\s*)[*-]\s+/gm;

function bold(line, key) {
  return line.split(/\*\*(.+?)\*\*/g).map((part, i) => (i % 2 ? <strong key={`${key}-${i}`} className="font-semibold">{part}</strong> : part));
}

export function MessageText({ text }) {
  if (!text) return null;
  return bold(text.replace(BULLET, '$1• '), 'b');
}
