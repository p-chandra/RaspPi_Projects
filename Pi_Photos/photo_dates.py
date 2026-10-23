"""Read capture timestamps without changing image bytes or filesystem dates."""
from datetime import datetime, timedelta, timezone
import re


def taken_time_ns(image):
    try:
        exif = image.getexif()
        details = exif.get_ifd(0x8769) if 0x8769 in exif else {}
        for date_tag, offset_tag, subsecond_tag in ((0x9003, 0x9011, 0x9291), (0x9004, 0x9012, 0x9292)):
            value = details.get(date_tag, exif.get(date_tag))
            if not value:
                continue
            try:
                moment = datetime.strptime(str(value).strip(' \x00'), '%Y:%m:%d %H:%M:%S')
                if not 1900 <= moment.year <= 2200:
                    continue
                offset = str(details.get(offset_tag, exif.get(offset_tag, ''))).strip(' \x00')
                if re.fullmatch(r'[+-]\d{2}:\d{2}', offset):
                    minutes = int(offset[1:3]) * 60 + int(offset[4:6])
                    moment = moment.replace(tzinfo=timezone(timedelta(minutes=minutes if offset[0] == '+' else -minutes)))
                # Without an embedded offset, interpret the camera clock in Pi local time.
                fraction = str(details.get(subsecond_tag, exif.get(subsecond_tag, ''))).strip(' \x00')
                ns = int((fraction + '000000000')[:9]) if fraction.isdigit() else 0
                return int(moment.timestamp()) * 1_000_000_000 + ns
            except (ValueError, OverflowError, OSError):
                continue
    except (AttributeError, TypeError, ValueError, OSError, SyntaxError):
        pass
    return None
