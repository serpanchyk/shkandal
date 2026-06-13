import type { LatestEvent } from "@/lib/api";

function eventDate(event: LatestEvent) {
  return [event.event_day, event.event_month, event.event_year].filter(Boolean).join(".");
}

function EventList({ events, hidden = false }: { events: LatestEvent[]; hidden?: boolean }) {
  return (
    <ul aria-hidden={hidden}>
      {events.map((event, index) => (
        <li key={`${event.title_uk}-${eventDate(event)}-${index}`}>
          <time>{eventDate(event)}</time>
          <strong>{event.title_uk}</strong>
          {event.location_uk ? <span>{event.location_uk}</span> : null}
        </li>
      ))}
    </ul>
  );
}

export function EventTicker({ events }: { events: LatestEvent[] }) {
  if (!events.length) {
    return <p className="eventTickerEmpty">Нові датовані події з’являться тут.</p>;
  }

  return (
    <aside aria-label="Останні події" className="eventTicker">
      <div className="eventTickerTrack">
        <EventList events={events} />
        <EventList events={events} hidden />
      </div>
    </aside>
  );
}
