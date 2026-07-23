# Third-party notices

The repository's MIT license covers repository-owned code. Third-party dependencies and adapted
code retain the terms described here and in their distributed packages.

## Remotion

The rendering engine depends on `remotion` and `@remotion/*` packages. Remotion uses its own
two-tier license: eligible individuals and small organizations may use it under the free terms;
other for-profit organizations may need a company license. Review the exact license shipped with
the installed package and the current [Remotion license page](https://www.remotion.pro/license)
before commercial use. The repository's MIT license does not replace those terms.

## OpenScreen zoom and focus algorithms

Parts of `engine/src/Timeline.tsx` adapt zoom-region strength, focus clamping, cubic-bezier,
and spring behavior from [OpenScreen](https://github.com/siddharthvaddem/openscreen), pinned for
attribution at commit `f57e36e25448b5af6c7b1b271066fe5beb9b8a49`.

MIT License

Copyright (c) 2025 Siddharth Vaddem

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge, publish, distribute,
sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT
OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
