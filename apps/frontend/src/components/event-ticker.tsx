"use client";

import { useEffect, useState } from "react";

import type { LatestEvent } from "@/lib/api";

const rotationDelayMs = 3750;

function eventDate(event: LatestEvent) {
  return [event.event_day, event.event_month, event.event_year].filter(Boolean).join(".");
}

function eventPosition(index: number, activeIndex: number, eventCount: number) {
  if (index === activeIndex) return "current";
  if (index === (activeIndex - 1 + eventCount) % eventCount) return "previous";
  if (index === (activeIndex + 1) % eventCount) return "next";
  return "hidden";
}

export function EventTicker({ events }: { events: LatestEvent[] }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (events.length < 2 || paused || reducedMotion.matches) return;

    const interval = window.setInterval(() => {
      setActiveIndex((index) => (index + 1) % events.length);
    }, rotationDelayMs);

    return () => window.clearInterval(interval);
  }, [events.length, paused]);

  if (!events.length) {
    return <p className="eventTickerEmpty">Нові датовані події з’являться тут.</p>;
  }

  return (
    <aside
      aria-label="Останні події"
      className="eventTicker"
      onBlur={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      <ul>
        {events.map((event, index) => {
          const position = eventPosition(index, activeIndex, events.length);
          return (
            <li
              aria-hidden={position === "hidden"}
              className={`eventTickerItem eventTickerItem--${position}`}
              key={`${event.title_uk}-${eventDate(event)}-${index}`}
            >
              <time>{eventDate(event)}</time>
              <strong>{event.title_uk}</strong>
              {event.location_uk ? <span>{event.location_uk}</span> : null}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
