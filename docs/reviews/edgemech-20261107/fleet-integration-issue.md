EdgeMech registration revealed incomplete integration in the first local gate:

- The embeddings rollout intentionally requires every canonical fleet member,
  so adding EdgeMech without a scoped entry breaks rollout loading.
- The general agent scope test assumes new members support all generic
  capabilities. EdgeMech deliberately has disabled, unverified adapters.
- The ingredient-inventory contract requires excluded corpora to explicitly
  declare `not_applicable`; the initial scaffold used `disabled` everywhere.

Reproduced on CLAW feature commit daad1515c61b5425f9874c76a01ecdc79fab13b6.
The interrupted gate recorded 13 failures from these three causes, 842 passes
and 13 skips. It was stopped after the failures to repair the integration.

Fix within #953: add an honest conditional packet-view rollout entry without
claiming an implemented embedding pipeline; preserve disabled capability scope
in the agent contract test; mark the medium-ingredient inventory inapplicable
to EdgeMech with its actual reason. Update the scaffold helper consistently.
Then run focused affected tests and the complete final repository gate.
