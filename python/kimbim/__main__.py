# SPDX-License-Identifier: GPL-3.0-or-later
import sys

if sys.argv[1:2] == ["serve"]:  # the agent worker (D102); the CLI's own `serve` parsing arrives with its rebuild
    from .agent.worker import main as serve_main

    sys.exit(serve_main(sys.argv[2:]))

from .cli import main  # noqa: E402

sys.exit(main())
