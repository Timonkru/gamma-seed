"""Pine aus den GESPEICHERTEN Tages-Leveln regenerieren — ohne neuen Datenabruf.
(Für Template-/Layout-Änderungen; die Level bleiben exakt die eingefrorenen.)"""
from datetime import date

from build_seed import gen_auto_pine, load_stored_levels

levels = load_stored_levels()
out = gen_auto_pine(levels, date.today())
print(f"Regeneriert (ohne Neuberechnung): {out}")
for p, v in sorted(levels.items()):
    print(f"  {p}: Flip {v['flip']:.0f} | CW {v['cw']:.0f} | PW {v['pw']:.0f} "
          f"| 0DTE-Flip {v.get('nflip', 0):.0f}")
