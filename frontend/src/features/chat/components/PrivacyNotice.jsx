import { Icon } from '../../../components/ui/index.js';
import { useGetMeQuery } from '../../account/accountApi.js';

/** What happens to the conversation: retention, who can read it, how it's used. */
export function PrivacyNotice({ className = '' }) {
  const { data: me } = useGetMeQuery();
  if (!me?.privacy) return null;
  return (
    <p className={`flex items-start gap-1.5 text-[11px] leading-relaxed text-slate-400 ${className}`}>
      <Icon name="lock" className="mt-px size-3 shrink-0" />
      {me.privacy.notice}
    </p>
  );
}
