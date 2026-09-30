import { Section } from '../../../components/ui/index.js';

export function OpenQuestions({ questions }) {
  if (!questions.length) return null;
  return (
    <Section title="Still open" icon="question">
      <ul className="space-y-2">
        {questions.map((question, i) => (
          <li key={i} className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-slate-700 ring-1 ring-amber-200">
            “{question}”
          </li>
        ))}
      </ul>
    </Section>
  );
}
