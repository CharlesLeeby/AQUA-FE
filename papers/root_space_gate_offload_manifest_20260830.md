# Root-space gate offload manifest (2026-08-30)

Purpose: satisfy the frozen fair-stability v9 pre-start requirement of at
least 5 GiB free on `/` without deleting user data or moving the active
OpenAI/Claude VS Code extensions.

All source paths below are symbolic links to the preserved directory on
`/mnt/data`.  Restoration is therefore reversible by copying the target back
and replacing the link.

Primary offload roots:

`/mnt/data/AQUA-FE_WS/storage_offload/root_space_gate_20260830`

`/media/ma/Data/AQUA-FE_WS_storage_offload/root_space_gate_20260830`

Moved paths:

- `/home/ma/.vscode/extensions/ms-ceintl.vscode-language-pack-zh-hans-1.131.2026072717`
- `/home/ma/.vscode/extensions/anthropic.claude-code-2.1.239-linux-x64` (second offload root)
- `/home/ma/.vscode/extensions/anthropic.claude-code-2.1.240-linux-x64` (second offload root)
- `/home/ma/.vscode/extensions/anthropic.claude-code-2.1.241-linux-x64` (second offload root)
- `/home/ma/.vscode/extensions/anthropic.claude-code-2.1.243-linux-x64`
- `/home/ma/.vscode/extensions/anthropic.claude-code-2.1.246-linux-x64`
- `/home/ma/.vscode/extensions/anthropic.claude-code-2.1.248-linux-x64`
- `/home/ma/.vscode/extensions/anthropic.claude-code-2.1.250-linux-x64`
- `/home/ma/.vscode/extensions/openai.chatgpt-26.818.41509-linux-x64`
- `/home/ma/.vscode/extensions/openai.chatgpt-26.818.41705-linux-x64`
- `/home/ma/.vscode/extensions/openai.chatgpt-26.820.80927-linux-x64`
- `/home/ma/.vscode/extensions/openai.chatgpt-26.825.31414-linux-x64`
- `/home/ma/.vscode/extensions/openai.chatgpt-26.825.32147-linux-x64`
- `/home/ma/ma_old/robot_control_system/build` (second offload root)
- `/home/ma/ma_old/robot_sim/build` (second offload root)

Explicitly retained active extension directories:

- `/home/ma/.vscode/extensions/openai.chatgpt-26.825.41651-linux-x64`
- `/home/ma/.vscode/extensions/anthropic.claude-code-2.1.251-linux-x64`

Post-move verification observed every listed source as a readable directory
symlink.  The second balancing pass mounted `/dev/sda1` at `/media/ma/Data`
and moved the five entries marked above from the first offload root to the
second.  Free-space observations immediately afterward were 6,284,800,000
bytes on `/`, 6,714,863,616 bytes on `/mnt/data`, and 381,243,392 bytes on
`/media/ma/Data`.
