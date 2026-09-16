"""
Destinations: one package per spreadsheet this tool is pointed at.

Each subpackage here describes **one** sheet, concretely. ``settlement`` is the
workbook this tool was written against; a second sheet is a sibling beside it::

    APITool/plugins/settlement/     this workbook's tabs, headers, glyphs
    APITool/plugins/mygooglesheet/  someone else's, entirely their own

**A plugin is allowed to be utterly specific.** It hardcodes real tab names,
real column letters, real row numbers -- that is the point of it, not a
shortcoming. Nothing in here should grow a configuration format or a template
layer: a second sheet gets a second directory, not a settings file.

What a plugin must NOT do is leak upward. Everything above this package --
``journal``, ``market``, ``ship``, ``service``, ``daemon``, the ``sheets``
toolkit and the ``google`` vendor adapter -- must be able to run with this
whole directory deleted. Two checks hold that line, and both go red rather
than quietly passing:

    tests/test_destination_seam.py
        removing a plugin breaks ONLY that plugin's features
    tests/test_market_data.py, the composition-layer check
        modules above may reach a plugin, but only at function scope

The shared mechanics a plugin builds on -- A1 arithmetic, the write guard,
range bounds, quantity parsing -- live in ``APITool.sheets`` and are not
copied here. When a second plugin needs something the first already wrote, it
**moves** into that package rather than being duplicated; two copies that must
agree, with nothing making them agree, is how they drift.
"""
