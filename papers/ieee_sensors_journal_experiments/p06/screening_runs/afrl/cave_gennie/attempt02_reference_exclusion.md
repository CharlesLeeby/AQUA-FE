# P06 AFRL cave_gennie attempt02 reference exclusion

- Stopped at: `2026-08-05T00:11:21+08:00`
- Terminal classification: `STOPPED_REFERENCE_INELIGIBLE`
- Scientific screening result produced: `false`
- Learned or VINS trajectory outcome read: `false`

The direct compressed-image adapter was operating correctly, with continuous
frame indices and bounded temporary storage. It was intentionally interrupted
after the frozen reference-support audit showed that all 15 fixed 45 s windows
fail the G0 reference-only gate under the preregistered AFRL 5 Hz evaluation
rate and 0.5 s gap limit. Continuing the remaining sequence could not produce
an eligible confirmatory window. The stop decision did not use KLT scores,
texture strata, learned output, proposed-arm output, VINS, APE, or RPE.

The runner's mechanical status is `FAILED` with return code 254 because SIGINT
propagated as `KeyboardInterrupt`. Governance resolution is the versioned
reference exclusion above, not an algorithm or infrastructure failure.

Archived partial evidence:

```text
9e38075c2c10c05e9de293dea1371122acba6a3952c0fd0fc97b55a8cb3b4dac  partial_metrics.csv  size=735720 rows=1224 frames=0..1223
579d6f70860c842a64f00d0ff9d59a9864a956d60e5e3878982d92539aaa6b15  features.bag       size=27762223 messages=1224 (deleted)
55ea1691e69cf56eb280e1f801d4dc42d9727a0b0796878d2183d1288871dc3a  afrl_p06_camera.yaml
bfa54d2c541e94b299c1bc5b42fee8855e20ab9b24e94e420ad06e055ee3c1ed  direct_command.txt
6e30e20621e8692048dcd71934b3858d3c6c9b8128ac57e23b4cd80ed6a53eeb  process.log
1197c73d466d1274c15b0b795fb66768947da7cc0bde225529b02fe46ef6a4a0  command.txt
67ba5683899b35e363b3892a50e511599e59a7d302f7dc22206acc1426b4d7e5  screening_run.json
```

The failed disk-expanding attempt01 remains unchanged. `bus_outside` and
`cemetery` continue as the AFRL reference-bearing candidates; their unsupported
fixed windows will be removed by the same frozen v2 mask before percentiles.
