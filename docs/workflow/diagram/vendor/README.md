# vendor/

React 18.3.1 UMD builds, byte-identical to:

- https://unpkg.com/react@18.3.1/umd/react.production.min.js
- https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js

They are committed so `build.mjs` never touches the network. The dc-runtime
(`src/support.js`) is pinned to these exact versions — if you refresh them,
refresh both together and re-check the pinned URLs at the bottom of
`src/support.js` (`REACT_URL` / `REACT_DOM_URL`).

MIT licensed, © Meta Platforms, Inc. and affiliates.
