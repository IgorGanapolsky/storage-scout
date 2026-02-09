import argparse
from .engine import Engine, load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous Outreach Engine")
    parser.add_argument("--config", default="autonomy/config.json")
    args = parser.parse_args()

    config = load_config(args.config)
    engine = Engine(config)
    result = engine.run()
    print(result)


if __name__ == "__main__":
    main()
