import { useState } from 'react';
import type { KeyboardEvent } from 'react';
import type { Shot, XgRacePoint } from './types';

export function useShotInteraction() {
  const [hoveredShotId, hover] = useState<string | null>(null);
  const [selectedShotId, select] = useState<string | null>(null);
  return { hoveredShotId, selectedShotId, activeShotId: hoveredShotId ?? selectedShotId, hover, select,
    clear: () => { hover(null); select(null); } };
}
export type ShotInteraction = ReturnType<typeof useShotInteraction>;
export function shotEvents(id: string, interaction: ShotInteraction) {
  return {
    onMouseEnter: () => interaction.hover(id), onMouseLeave: () => interaction.hover(null),
    onFocus: () => interaction.hover(id), onBlur: () => interaction.hover(null),
    onClick: () => interaction.select(id),
    onKeyDown: (event: KeyboardEvent<SVGGElement>) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); interaction.select(id); }
      if (event.key === 'Escape') { event.stopPropagation(); interaction.clear(); }
    },
  };
}
export function raceStateForShot(shot: Shot, points: readonly XgRacePoint[]) {
  // The other team's plateau at this event is a state, not a shot by that team.
  return points.find(point => point.event_id === shot.event_id && point.team_id === shot.team_id);
}
