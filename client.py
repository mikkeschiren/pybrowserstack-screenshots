""" Initiate jobs at Browserstack Screenshots and downloads the images when
    they are complete. Optionally renames and slices images for use with
    PhantomCSS visual regression testing tool """

import math, os, sys, time, re, getopt
from PIL import Image
import requests
import browserstack_screenshots
from ConfigParser import SafeConfigParser

try:
    import simplejson as json
except ImportError:
    import json

parser = SafeConfigParser()
parser.read('config.ini')

MAX_RETRIES = 20
OUTPUT_DIR_PHANTOMCSS = './output-phantomcss'
output_dir = './output'
phantomcss = False
EXTERNALURL = 'localhost/'

def _build_sliced_filepath(filename, slice_count):
    """ append slice_count to the end of a filename """
    root = os.path.splitext(filename)[0]
    ext = os.path.splitext(filename)[1]
    new_filepath = ''.join((root, str(slice_count), ext))
    return _build_filepath_for_phantomcss(new_filepath)

def _build_filepath_for_phantomcss(filepath):
    """ Prepare screenshot filename for use with phantomcss.
        ie, append 'diff' to the end of the file if a baseline exists """
    try:
        if os.path.exists(filepath):
            new_root = '.'.join((os.path.splitext(filepath)[0], 'diff'))
            ext = os.path.splitext(filepath)[1]
            diff_filepath = ''.join((new_root, ext))
            if os.path.exists(diff_filepath):
                print 'removing stale diff: {0}'.format(diff_filepath)
                os.remove(diff_filepath)
            return diff_filepath
        else:
            return filepath
    except OSError, e:
        print e

def _build_filename_from_browserstack_json(j):
    """ Build a useful filename for an image from the screenshot json metadata """
    filename = ''
    device = j['device'] if j['device'] else 'Desktop'
    if j['state'] == 'done' and j['image_url']:
        detail = [device, j['os'], j['os_version'],
                j['browser'], j['browser_version'], '.jpg']
        filename = '_'.join(item.replace(" ", "_") for item in detail if item)
    else:
        print 'screenshot timed out, ignoring this result'
    return filename

def _long_image_slice(in_filepath, out_filepath, slice_size):
    """ Slice an image into parts slice_size tall. """
    print 'slicing image: {0}'.format(in_filepath)
    img = Image.open(in_filepath)
    width, height = img.size
    upper = 0
    left = 0
    slices = int(math.ceil(height/slice_size))

    count = 1
    for slice in range(slices):
        # if we are at the end, set the lower bound to be the bottom of the image
        if count == slices:
            lower = height
        else:
            lower = int(count * slice_size)
        # set the bounding box! The important bit
        bbox = (left, upper, width, lower)
        working_slice = img.crop(bbox)
        upper += slice_size
        # save the slice
        new_filepath = _build_sliced_filepath(out_filepath, count)
        working_slice.save(new_filepath)
        count += 1

def _read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (EOFError, IOError), e:
        print e
        return {}

def _mkdir(path):
    try:
        os.makedirs(path)
    except OSError, e:
        if e.errno != 17:
            raise

def _download_file(uri, filename):
    try:
        with open(filename, 'wb') as handle:
            request = requests.get(uri, stream=True)
            for block in request.iter_content(1024):
                if not block:
                    break
                handle.write(block)
    except IOError, e:
        print e

def _purge(dir, pattern, reason=''):
    """ delete files in dir that match pattern """
    for f in os.listdir(dir):
        if re.search(pattern, f):
            print "Purging file {0}. {1}".format(f, reason)
            os.remove(os.path.join(dir, f))

def retry(tries, delay=3, backoff=2):
    """Retries a function or method until it returns True."""

    if backoff <= 1:
        raise ValueError("backoff must be greater than 1")

    tries = math.floor(tries)
    if tries < 0:
        raise ValueError("tries must be 0 or greater")

    if delay <= 0:
        raise ValueError("delay must be greater than 0")

    def deco_retry(f):
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay

            rv = f(*args, **kwargs) # first attempt
            while mtries > 0:
                if rv is True:
                    return True

                mtries -= 1
                time.sleep(mdelay)
                mdelay *= backoff

                rv = f(*args, **kwargs) # Try again
            print str(tries) + " attempts. Abandoning."
            return False # Ran out of tries
        return f_retry
    return deco_retry

@retry(MAX_RETRIES, 2, 2)
def retry_get_screenshots(s, job_id):
    return get_screenshots(s, job_id)

def get_screenshots(s, job_id):
    screenshots_json = s.get_screenshots(job_id)
    if screenshots_json:
        _mkdir(output_dir)
        _mkdir(EXTERNALURL)
        try:
            print 'Screenshot job complete. Saving files.'
            _purge(output_dir, '.diff', 'stale diff')
            for i in screenshots_json['screenshots']:
                filename = _build_filename_from_browserstack_json(i)
                base_image = os.path.join(output_dir, filename)
                if filename:
                    _download_file(i['image_url'], base_image)
                if phantomcss and os.path.isfile(base_image):
                    # slice the image. slicing on css selector could be better..
                    _long_image_slice(base_image, base_image, 300)
                    os.remove(base_image)
            print 'Done saving.'
            filenames = os.listdir(output_dir)
            for filename in filenames:
               print os.path.join(EXTERNALURL, filename)
            return True
        except OSError, e:
            print e
            return False
    else:
        print "Screenshots job incomplete. Waiting before retry."
        return False

class ScreenshotIncompleteError(Exception):
    pass

def main(argv):
    api_user = parser.get('api', 'user')
    api_token = parser.get('api', 'token')

    """ Do not edit below this line """

    def usage():
        print 'Usage:\n-c, --config <config_file>\n-p, --phantomcss\n-o, --output <output_dir>\n-m, --externalurl <external_url>'

    try:
        opts, args = getopt.getopt(argv, "c:p:o:e", ["config=", "phantomcss", "output=", "externalurl="])
    except getopt.GetoptError:
        usage()
        sys.exit(2)

    config_file = ''
    for opt, arg in opts:
        if opt in ("-c", "--config"):
            config_file = arg
        if opt in ("-p", "--phantomcss"):
            global phantomcss, output_dir
            phantomcss = True
            output_dir = OUTPUT_DIR_PHANTOMCSS
        if opt in ("-e", "--externalurl"):
            EXTERNALURL = arg
        if opt in ("-o", "--output"):
            output_dir = arg

    auth = (api_user, api_token)
    config = _read_json(config_file) if config_file else None
    print 'using config {0}'.format(config_file)
    s = browserstack_screenshots.Screenshots(auth=auth, config=config)
    generate_resp_json = s.generate_screenshots()
    job_id = generate_resp_json['job_id']
    print "started job id: {0}".format(job_id)
    if not retry_get_screenshots(s, job_id):
        print """ Failed. The job was not complete at Browserstack after x
              attempts. You may need to increase the number of retry attempts """

if __name__ == "__main__":
    main(sys.argv[1:])
