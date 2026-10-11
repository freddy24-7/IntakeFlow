"""Generate the synthetic document set with ground truth.

uv run python scripts/generate_synthetic.py --documents 200 --seed 42
"""

import argparse
import json
from pathlib import Path

from synthetic.build import generate
from synthetic.write import manifest, write_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--documents", type=int, default=200)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"))
    arguments = parser.parse_args()

    dataset = generate(arguments.documents, arguments.seed)
    write_dataset(dataset, arguments.out)
    print(json.dumps(manifest(dataset), indent=2))
    print(f"Written to {arguments.out}")


if __name__ == "__main__":
    main()
