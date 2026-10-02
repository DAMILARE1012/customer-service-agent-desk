import { useDispatch, useSelector } from 'react-redux';
import { Icon } from '../../../components/ui/index.js';
import { searchChanged, selectSearch } from '../deskSlice.js';

export function QueueSearch() {
  const dispatch = useDispatch();
  const search = useSelector(selectSearch);

  return (
    <label className="relative block">
      <span className="sr-only">Search conversations</span>
      <Icon name="search" className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-slate-400" />
      <input
        type="search"
        value={search}
        onChange={(e) => dispatch(searchChanged(e.target.value))}
        placeholder="Search customer or topic"
        className="w-full rounded-lg border-0 bg-white py-2 pr-3 pl-8 text-sm ring-1 ring-slate-200 placeholder:text-slate-400 focus:ring-2 focus:ring-indigo-500 focus:outline-none"
      />
    </label>
  );
}
