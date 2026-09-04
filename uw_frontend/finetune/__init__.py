"""Underwater domain-adaptation fine-tuning for the XFeat learned matcher.

This package fine-tunes the stock XFeat weights on underwater imagery via the
upstream self-supervised homography scheme (no GT poses required), with an added
physically-motivated underwater degradation augmentation. The produced weights
(``xfeat_uw.pt``) drop directly into ``uw_frontend.matchers.xfeat_adapter``.
"""
