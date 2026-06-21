import { resolveFrontendRoute } from "../../navigation/FrontendRouter";
import { createFixtureTrackingEvent } from "../../tracking/createFixtureTrackingEvent";

export function OrderSummaryPanel() {
  const route = resolveFrontendRoute("/orders");
  const event = createFixtureTrackingEvent("fixture.order.summary.viewed");

  return {
    routeLabel: route?.labelKey ?? "fixture.navigation.unknown",
    analyticsName: event.name,
  };
}
