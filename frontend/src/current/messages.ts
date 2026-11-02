import { useI18n } from '../i18n';
import type { Language } from '../locales';

const en = {
  nav: 'Current Competitions', historical: 'Historical Match Lab', workspace: 'Explore Touchline',
  skip: 'Skip to competition overview', title: 'Current competitions', eyebrow: 'A NEW VIEW OF THE SEASON',
  intro: 'Fixtures, results and the league picture. A local UI prototype, not live coverage.',
  demo: 'DEMO DATA — SYNTHETIC', demoNote: 'Invented teams, fixtures and scores. Not real 2026/27 results. No live provider is connected.',
  prototype: 'UI PROTOTYPE', league: 'League phase', open: 'Open league overview', back: 'All current competitions',
  teams: 'Teams', matches: 'Matches', played: 'Played', rounds: 'Rounds', finished: 'Finished', timed: 'Scheduled',
  fixtures: 'Fixtures & results', standings: 'Standings', view: 'League view', team: 'Team', allTeams: 'All demo teams',
  round: 'Matchday', roundN: 'Matchday {round}', allRounds: 'All matchdays', from: 'From date (UTC)', to: 'To date (UTC)',
  reset: 'Reset filters', shown: '{shown} of {total} fixtures', rows: '{shown} of {total} teams',
  empty: 'No demo fixtures match these filters.', emptyTable: 'No demo standings available.',
  loading: 'Loading synthetic competition…', error: 'Unable to load the demo.', retry: 'Try again',
  noCompetitions: 'No demo competitions available.', missing: 'This demo competition is not available.',
  invalid: 'Some URL filters were invalid and have been ignored.', dateOrder: 'The end date must not be before the start date.',
  timezone: 'All fixture dates and times are UTC.', fixedClock: 'Fixed demo clock: {date}. Not provider freshness.',
  scope: 'Synthetic league phase only. Qualification and knockout rounds are not included.',
  tableScope: 'Table uses all finished demo fixtures; matchday/date filters apply only to the fixture list.',
  method: 'Demo methodology & limits', ranking: 'Demo ranking: points → goal difference → goals for → demo ID. Not UEFA tie-breakers. The invented draw does not model UEFA pots or country restrictions.',
  noEvents: 'Results-only demo. No Shot Map, Pass Map, Pressure Heatmap or player-event data.',
  top8: '1–8 · Top eight', playoff: '9–24 · Play-off places', outside: '25–36 · Outside qualifying places',
  position: 'Position', won: 'Won', drawn: 'Drawn', lost: 'Lost', gf: 'Goals for', ga: 'Goals against', gd: 'Goal difference', points: 'Points',
  caption: 'Synthetic league standings — 36 invented teams', scroll: 'Scroll the table horizontally for all statistics; team and position stay visible.', utc: 'UTC', footer: 'Synthetic prototype · no live integration · local development',
} as const;
type CurrentKey = keyof typeof en;
type CurrentMessages = { [K in CurrentKey]: string };
const ru: CurrentMessages = {
  nav: 'Текущие турниры', historical: 'Исторический Match Lab', workspace: 'Разделы Touchline',
  skip: 'Перейти к обзору турнира', title: 'Текущие турниры', eyebrow: 'НОВЫЙ ВЗГЛЯД НА СЕЗОН',
  intro: 'Календарь, результаты и таблица. Локальный прототип интерфейса, не live-покрытие.',
  demo: 'ДЕМО-ДАННЫЕ — СИНТЕТИЧЕСКИЕ', demoNote: 'Вымышленные команды, матчи и счета. Это не реальные результаты 2026/27. Live-провайдер не подключён.',
  prototype: 'ПРОТОТИП UI', league: 'Этап лиги', open: 'Открыть обзор турнира', back: 'Все текущие турниры',
  teams: 'Команды', matches: 'Матчи', played: 'Сыграно', rounds: 'Туры', finished: 'Завершён', timed: 'Запланирован',
  fixtures: 'Календарь и результаты', standings: 'Таблица', view: 'Вид турнира', team: 'Команда', allTeams: 'Все демо-команды',
  round: 'Тур', roundN: 'Тур {round}', allRounds: 'Все туры', from: 'С даты (UTC)', to: 'По дату (UTC)',
  reset: 'Сбросить фильтры', shown: 'Матчей: {shown} из {total}', rows: 'Команд: {shown} из {total}',
  empty: 'Нет демо-матчей по этим фильтрам.', emptyTable: 'Демо-таблица недоступна.',
  loading: 'Загружаем синтетический турнир…', error: 'Не удалось загрузить демо.', retry: 'Повторить',
  noCompetitions: 'Нет доступных демо-турниров.', missing: 'Этот демо-турнир недоступен.',
  invalid: 'Некорректные URL-фильтры проигнорированы.', dateOrder: 'Конечная дата не должна быть раньше начальной.',
  timezone: 'Все даты и время матчей указаны в UTC.', fixedClock: 'Фиксированные демо-часы: {date}. Не свежесть данных провайдера.',
  scope: 'Только синтетический этап лиги. Квалификация и плей-офф не включены.',
  tableScope: 'Таблица учитывает все завершённые демо-матчи; фильтры тура и дат действуют только на календарь.',
  method: 'Методика и ограничения демо', ranking: 'Демо-сортировка: очки → разница голов → забитые голы → демо-ID. Это не тай-брейкеры UEFA. Вымышленная жеребьёвка не учитывает корзины и ограничения по странам.',
  noEvents: 'Демо содержит только результаты. Нет Shot Map, Pass Map, Pressure Heatmap и событий игроков.',
  top8: '1–8 · Первая восьмёрка', playoff: '9–24 · Стыковые места', outside: '25–36 · Вне проходных мест',
  position: 'Позиция', won: 'Победы', drawn: 'Ничьи', lost: 'Поражения', gf: 'Забито', ga: 'Пропущено', gd: 'Разница голов', points: 'Очки',
  caption: 'Синтетическая таблица — 36 вымышленных команд', scroll: 'Прокрутите таблицу по горизонтали для всех показателей; команда и позиция остаются видимыми.', utc: 'UTC', footer: 'Синтетический прототип · без live-интеграции · локальная разработка',
};
const es: CurrentMessages = {
  nav: 'Competiciones actuales', historical: 'Match Lab histórico', workspace: 'Explorar Touchline',
  skip: 'Ir al resumen de la competición', title: 'Competiciones actuales', eyebrow: 'OTRA MIRADA A LA TEMPORADA',
  intro: 'Calendario, resultados y clasificación. Prototipo local, no cobertura en directo.',
  demo: 'DATOS DEMO — SINTÉTICOS', demoNote: 'Equipos, partidos y marcadores inventados. No son resultados reales de 2026/27. Sin proveedor en directo.',
  prototype: 'PROTOTIPO UI', league: 'Fase de liga', open: 'Abrir resumen de la liga', back: 'Todas las competiciones actuales',
  teams: 'Equipos', matches: 'Partidos', played: 'Jugados', rounds: 'Jornadas', finished: 'Finalizado', timed: 'Programado',
  fixtures: 'Calendario y resultados', standings: 'Clasificación', view: 'Vista de la liga', team: 'Equipo', allTeams: 'Todos los equipos demo',
  round: 'Jornada', roundN: 'Jornada {round}', allRounds: 'Todas las jornadas', from: 'Desde (UTC)', to: 'Hasta (UTC)',
  reset: 'Restablecer filtros', shown: '{shown} de {total} partidos', rows: '{shown} de {total} equipos',
  empty: 'No hay partidos demo con estos filtros.', emptyTable: 'No hay clasificación demo disponible.',
  loading: 'Cargando competición sintética…', error: 'No se pudo cargar la demo.', retry: 'Reintentar',
  noCompetitions: 'No hay competiciones demo disponibles.', missing: 'Esta competición demo no está disponible.',
  invalid: 'Se han ignorado algunos filtros de URL no válidos.', dateOrder: 'La fecha final no puede ser anterior a la inicial.',
  timezone: 'Todas las fechas y horas de los partidos están en UTC.', fixedClock: 'Reloj demo fijo: {date}. No indica actualización del proveedor.',
  scope: 'Solo fase de liga sintética. No incluye clasificación previa ni eliminatorias.',
  tableScope: 'La tabla incluye todos los partidos demo finalizados; jornada y fechas solo filtran el calendario.',
  method: 'Método y límites de la demo', ranking: 'Orden demo: puntos → diferencia de goles → goles a favor → ID demo. No son desempates UEFA. El sorteo inventado no modela bombos ni restricciones por país.',
  noEvents: 'Demo solo de resultados. Sin Shot Map, Pass Map, Pressure Heatmap ni eventos de jugadores.',
  top8: '1–8 · Ocho primeros', playoff: '9–24 · Plazas de play-off', outside: '25–36 · Fuera de clasificación',
  position: 'Posición', won: 'Ganados', drawn: 'Empatados', lost: 'Perdidos', gf: 'Goles a favor', ga: 'Goles en contra', gd: 'Diferencia de goles', points: 'Puntos',
  caption: 'Clasificación sintética — 36 equipos inventados', scroll: 'Desplaza la tabla horizontalmente para ver todas las estadísticas; equipo y posición permanecen visibles.', utc: 'UTC', footer: 'Prototipo sintético · sin integración en directo · desarrollo local',
};
export const currentMessages: Record<Language, CurrentMessages> = { en, ru, es };
export function useCurrentText() {
  const { language, count } = useI18n();
  return { language, count, ct: (key: CurrentKey, params: Record<string, string | number> = {}) =>
    currentMessages[language][key].replace(/\{(\w+)\}/g, (_, name: string) => String(params[name] ?? `{${name}}`)) };
}
