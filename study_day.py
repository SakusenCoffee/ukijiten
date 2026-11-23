"""Local study dates with a configurable wall-clock cutoff after midnight."""
from datetime import datetime,timedelta


def validate_cutoff(value):
    if type(value) is not int or not 0<=value<=23:
        raise ValueError('Day cutoff must be a whole number from 0 to 23 hours.')
    return value


def study_date(stamp=None, cutoff=0):
    validate_cutoff(cutoff)
    stamp=stamp or datetime.now().astimezone()
    if stamp.tzinfo is not None:stamp=stamp.astimezone()
    return stamp.date()-timedelta(days=int(stamp.hour<cutoff))
