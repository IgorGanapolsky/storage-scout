import argparse
import sys
from pathlib import Path

# Support running as a script: `python3 autonomy/run.py`
if __package__ is None:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autonomy.engine import Engine, load_config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous Outreach Engine")
    parser.add_argument("--config", default="autonomy/state/config.ai-seo.live.json")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    config_arg = Path(args.config)
    config_path = config_arg if config_arg.is_absolute() else (repo_root / config_arg).resolve()

    config = load_config(str(config_path))
    engine = Engine(config)
    result = engine.run()
    print(result)


if __name__ == "__main__":
    main()
