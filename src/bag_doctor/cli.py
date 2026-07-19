import argparse
from pathlib import Path
from .analyzer import analyze_bag

def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a ROS 2 bag in place")
    parser.add_argument("--bag", required=True, type=Path)
    args = parser.parse_args()
    if not args.bag.is_absolute() or not args.bag.exists():
        parser.error("--bag must be an existing absolute path")
    print(analyze_bag(args.bag).model_dump_json(indent=2))
