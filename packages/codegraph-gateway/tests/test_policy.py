from __future__ import annotations

import unittest

from agent_code_router_codegraph_gateway.policy import classify_graph_request


class PolicyTests(unittest.TestCase):
    def test_architecture_question_with_quotes_is_allowed(self) -> None:
        decision = classify_graph_request('How does "CheckoutService" reach PaymentGateway?')
        self.assertTrue(decision.allowed)

    def test_http_architecture_question_is_allowed(self) -> None:
        decision = classify_graph_request("How does HTTP request travel through OkHttp?")
        self.assertTrue(decision.allowed)

    def test_literal_lookup_is_redirected(self) -> None:
        decision = classify_graph_request('Where is "/api/login" used?')
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.recommended_tool_family, "rg_fd")


if __name__ == "__main__":
    unittest.main()
