from __future__ import annotations

from uw_frontend.matchers.lightglue_adapter import SuperPointLightGlueMatcher
from uw_frontend.matchers.loftr_adapter import LoFTRMatcher
from uw_frontend.matchers.xfeat_adapter import XFeatMatcher


def main() -> int:
    for cls in [XFeatMatcher, SuperPointLightGlueMatcher, LoFTRMatcher]:
        status = cls.availability()
        label = "available" if status.available else "unavailable"
        print(f"{cls.name}: {label} ({status.reason})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
