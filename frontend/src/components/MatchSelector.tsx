import { useEffect, useId, useRef, useState } from 'react';
import type { MatchOverview } from '../types';
import { useI18n } from '../i18n';
import { filterMatches } from '../search';

export function MatchSelector({ matches, selected, onSelect }: {
  matches: MatchOverview[]; selected: number | null; onSelect: (id: number) => void;
}) {
  const { t, date, stage, count } = useI18n();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(-1);
  const root = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  const results = filterMatches(matches, query, stage);
  const activeIndex = active < results.length ? active : -1;
  const current = matches.find(match => match.match_id === selected);
  function close() { setOpen(false); setQuery(''); setActive(-1); }
  useEffect(close, [selected]);
  useEffect(() => {
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) close(); };
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, []);
  useEffect(() => {
    if (open && active >= 0) document.getElementById(`${id}-option-${active}`)?.scrollIntoView?.({ block: 'nearest' });
  }, [active, open, id]);
  function choose(match: MatchOverview) { close(); onSelect(match.match_id); input.current?.focus(); }
  return <div className="match-selector" ref={root} onBlur={event => {
    if (!event.currentTarget.contains(event.relatedTarget)) close();
  }}>
    <label htmlFor={id}>{t('explore')}</label>
    <div className="combobox">
      <input ref={input} id={id} role="combobox" autoComplete="off" aria-autocomplete="list"
        aria-expanded={open} aria-controls={open ? `${id}-list` : undefined}
        aria-activedescendant={open && results[activeIndex] ? `${id}-option-${activeIndex}` : undefined}
        aria-describedby={`${id}-help`} placeholder={t('searchMatches')}
        value={open ? query : current?.match_label ?? ''}
        onFocus={() => { setOpen(true); setQuery(''); setActive(-1); }} onClick={() => setOpen(true)}
        onChange={event => { setQuery(event.target.value); setOpen(true); setActive(-1); }}
        onKeyDown={event => {
          if (event.key === 'Escape') { event.stopPropagation(); close(); }
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault(); setOpen(true);
            setActive(index => event.key === 'ArrowDown' ? Math.min(index + 1, results.length - 1)
              : index < 0 ? results.length - 1 : Math.max(0, index - 1));
          }
          if (event.key === 'Enter' && open && results.length) { event.preventDefault(); choose(results[Math.max(0, activeIndex)]); }
          if (event.key === 'Tab') close();
        }} />
      <span id={`${id}-help`} className="sr-only">{t('searchHelp')}</span>
      {open && <div className="match-popup">
        <p role="status">{results.length ? t('results', { count: count(results.length) }) : t('noMatches')}</p>
        <ul role="listbox" id={`${id}-list`} aria-label={t('explore')}>
          {results.map((match, index) => <li key={match.match_id} id={`${id}-option-${index}`}
            role="option" aria-selected={activeIndex === index} data-match-id={match.match_id}
            className={activeIndex === index ? 'active' : ''} onMouseEnter={() => setActive(index)}
            onMouseDown={event => event.preventDefault()} onClick={() => choose(match)}>
            <div><strong>{match.home_team_name} – {match.away_team_name}</strong>
              <span>{date(match.match_date)} · {stage(match.competition_stage_name)}</span></div>
            <span className="result-score">{match.display_score}</span>
          </li>)}
        </ul>
      </div>}
    </div>
    <p className="current-match"><span>{t('currentMatch')}</span>{current?.match_label ?? t(selected === null ? 'selectMatch' : 'unknownMatch')}</p>
  </div>;
}
