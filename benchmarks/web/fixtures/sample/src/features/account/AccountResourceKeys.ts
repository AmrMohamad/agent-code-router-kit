export const AccountResourceKeys = {
  title: "fixture.account.title",
  emptyState: "fixture.account.empty_state",
  supportLink: "fixture.navigation.support",
} as const;

export type AccountResourceKey = keyof typeof AccountResourceKeys;
