"""Enable stack dumps only in the diagnostic child interpreter."""

import faulthandler
import os
import sys

faulthandler.enable(all_threads=True)
faulthandler.dump_traceback_later(float(os.environ['MONTY_DIAG_DUMP_AFTER']), repeat=True)
print(f'DIAGNOSTIC Python {sys.version.split()[0]}: stack watchdog armed', file=sys.stderr, flush=True)
