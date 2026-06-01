// Single ESM entry that re-exports the widget's public surface AND
// the React runtime it needs.  The mount script then only has to
// make ONE network request to get everything it needs to render the
// LI.FI / Jumper widget, instead of waterfalling through esm.sh.
import * as React from "react";
import * as ReactDOM from "react-dom/client";
export { LiFiWidget } from "@lifi/widget";
export { React, ReactDOM };
