export interface FrontendRoute {
  path: string;
  labelKey: string;
}

export const FrontendRouter: FrontendRoute[] = [
  { path: "/orders", labelKey: "fixture.navigation.orders" },
  { path: "/account", labelKey: "fixture.navigation.account" },
  { path: "/support", labelKey: "fixture.navigation.support" },
];

export function resolveFrontendRoute(path: string): FrontendRoute | undefined {
  return FrontendRouter.find((route) => route.path === path);
}
