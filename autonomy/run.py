import argparse
import sys
from pathlib import Path

# Support running as a script: `python3 autonomy/run.py`
if __package__ is None:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autonomy.engine import Engine, load_config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous Outreach Engine")
    parser.add_argument("--config", default="autonomy/config.callcatcherops.json")
    args = parser.parse_args()

    config = load_config(args.config)
    engine = Engine(config)
    result = engine.run()
    print(result)


if __name__ == "__main__":
    main()
