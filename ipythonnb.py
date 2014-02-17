import os
from pelican import signals
from pelican.readers import MarkdownReader, HTMLReader, BaseReader

try:
    import json

    from IPython.config import Config
    from IPython.nbconvert.exporters import HTMLExporter

    from IPython.nbconvert.filters.highlight import _pygment_highlight
    from pygments.formatters import HtmlFormatter
except Exception as e:
    IPython = False
    raise e


# General settings, see add_reader at the end

settings = {}

# Strip HTML tags, for summary creation


from html.parser import HTMLParser


class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.fed = []

    def handle_data(self, d):
        self.fed.append(d)

    def get_data(self):
        return ''.join(self.fed)


def strip_tags(html):
    s = MLStripper()
    s.feed(html)
    return s.get_data()


# Fix CSS

CUSTOM_CSS = '''
<style type="text/css">

div.input_area {
    border: none;
    background: none;
    margin-left: 6px;
}

.cell {
    font-size: 14px;
}

pre.ipynb {
    padding: 3px 9.5px;
    font-size: 14px;
}

div.output_subarea {
    padding: 3px 0;
}

/* Forcing DataFrame table styles */
table.dataframe {
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 14px;
    line-height: 20px;
}

table.dataframe th, td {
    padding: 4px;
    text-align: left;
}

.anchor-link {
    display: none;
}

.anchor-link:hover {
    display: blockquote;
}

@media print{*{text-shadow:none !important;color:#000 !important;background:transparent !important;box-shadow:none !important;} a,a:visited{text-decoration:underline;} a[href]:after{content:" (" attr(href) ")";} abbr[title]:after{content:" (" attr(title) ")";} .ir a:after,a[href^="javascript:"]:after,a[href^="#"]:after{content:"";} pre,blockquote{border:1px solid #999;page-break-inside:avoid;} thead{display:table-header-group;} tr,img{page-break-inside:avoid;} img{max-width:100% !important;} @page {margin:0.5cm;}p,h2,h3{orphans:3;widows:3;} h2,h3{page-break-after:avoid;}}

</style>
'''


def custom_highlighter(source, language='ipython'):
    """
    Makes the syntax highliting from pygments have prefix(`highlight-ipynb`)
    So it does not break the themes pygments

    It modifies both the css and html
    """
    formatter = HtmlFormatter(cssclass='highlight-ipynb')
    output = _pygment_highlight(source, formatter, language)
    output = output.replace('<pre>', '<pre class="ipynb">')
    return output


class MyHTMLParser(HTMLReader._HTMLParser):
    """
    Extends Pelican HTMLReader._HTMLParser by including the summary of the content
    based on settings['SUMMARY_MAX_LENGTH'].
    Also stops the summary if founds any div containing ipython notebook code cells

    This is needed in order to generate valid HTML for the summary, because a simple split
    breaks the html generating errors on the theme.
    The downside is that the summary lenght is not exactly the specified, it includes
    complete div/p/li/etc tags.
    """
    def __init__(self, settings, filename):
        super(MyHTMLParser, self).__init__(settings, filename)

        self.summary = None

    def handle_starttag(self, tag, attrs):
        super(MyHTMLParser, self).handle_starttag(tag, attrs)

        if self.summary is None:
            # Check for any ipython cell tags
            # eg: <div class="cell border-box-sizing code_cell vbox">
            for k, v in attrs:
                if k == "class":
                    ipython_classes = ['cell', 'code_cell']
                    classes = v.split(' ')
                    if any(class_ in ipython_classes for class_ in classes):
                        self.summary = self._data_buffer + '...'

    def handle_endtag(self, tag):
        super(MyHTMLParser, self).handle_endtag(tag)

        if self.summary is None:
            self.wordcount = len(strip_tags(self._data_buffer).split(" "))
            if self.wordcount > self.settings['SUMMARY_MAX_LENGTH']:
                self.summary = self._data_buffer + '...'


class iPythonNB(BaseReader):
    enabled = True
    file_extensions = ['ipynb']

    def read(self, filepath):
        metadata = {}

        # Files
        filedir = os.path.dirname(filepath)
        filename = os.path.basename(filepath)
        metadata_filename = filename.split('.')[0] + '.ipynb-meta'
        metadata_filepath = os.path.join(filedir, metadata_filename)

        # Load metadata
        if os.path.exists(metadata_filepath):
            # Metadata is on a external file, process using Pelican MD Reader
            md_reader = MarkdownReader(self.settings)
            _content, metadata = md_reader.read(metadata_filepath)
        else:
            # Load metadata from ipython notebook file
            ipynb_file = open(filepath)
            metadata = json.load(ipynb_file)['metadata']

            # Fix metadata to pelican standars
            for key, value in metadata.items():
                del metadata[key]
                key = key.lower()
                metadata[key] = self.process_metadata(key, value)
            metadata['ipython'] = True

        # Convert ipython notebook to html
        config = Config({'CSSHTMLHeaderTransformer': {'enabled': True,
                         'highlight_class': '.highlight-ipynb'}})
        exporter = HTMLExporter(config=config, template_file='basic',
                                filters={'highlight2html': custom_highlighter})

        content, info = exporter.from_filename(filepath)

        # Process using Pelican HTMLReader
        content = '<body>{0}</body>'.format(content)  # So Pelican HTMLReader works
        parser = MyHTMLParser(self.settings, filename)
        parser.feed(content)
        parser.close()
        body = parser.body
        summary = parser.summary

        metadata['summary'] = summary

        # Remove some CSS styles, so it doesn't break the themes.
        def filter_tags(style_text):
            style_list = style_text.split('\n')
            exclude = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'ul', 'ol', '.rendered_html', '@media']
            style_list = [i for i in style_list if len(list(filter(i.startswith, exclude))) == 0]
            ans = '\n'.join(style_list)
            return '<style type=\"text/css\">{0}</style>'.format(ans)

        css = '\n'.join(filter_tags(css) for css in info['inlining']['css'])
        css = css + CUSTOM_CSS
        body = css + body

        return body, metadata


def add_reader(arg):
    global settings
    arg.settings['READERS']['ipynb'] = iPythonNB
    settings = arg.settings


def register():
    signals.initialized.connect(add_reader)
