export interface FixtureTrackingEvent {
  name: string;
  createdAtMs: number;
}

export function createFixtureTrackingEvent(name: string): FixtureTrackingEvent {
  return {
    name,
    createdAtMs: Date.now(),
  };
}
