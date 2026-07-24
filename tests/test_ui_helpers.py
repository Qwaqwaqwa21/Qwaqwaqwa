# coding: utf-8
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image
from io import BytesIO

from ui_helpers import stitch_figures_horizontally, scrollable_image_html


def make_fig(width_in, height_in, color):
    fig = plt.figure(figsize=(width_in, height_in))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(color)
    ax.set_xticks([])
    ax.set_yticks([])
    return fig


class TestStitchFiguresHorizontally:
    def test_combined_width_is_sum_of_parts(self):
        fig1 = make_fig(2, 3, 'red')
        fig2 = make_fig(3, 3, 'blue')
        png = stitch_figures_horizontally([fig1, fig2], dpi=100)
        plt.close(fig1)
        plt.close(fig2)

        img1_width = Image.open(BytesIO(png)).width
        # Re-render each individually to know expected component widths.
        fig1b = make_fig(2, 3, 'red')
        fig2b = make_fig(3, 3, 'blue')
        buf1, buf2 = BytesIO(), BytesIO()
        fig1b.savefig(buf1, format='png', dpi=100, bbox_inches='tight')
        fig2b.savefig(buf2, format='png', dpi=100, bbox_inches='tight')
        plt.close(fig1b)
        plt.close(fig2b)
        w1 = Image.open(buf1).width
        w2 = Image.open(buf2).width

        assert img1_width == w1 + w2

    def test_combined_height_is_max_of_parts(self):
        fig1 = make_fig(2, 3, 'red')
        fig2 = make_fig(2, 5, 'blue')
        png = stitch_figures_horizontally([fig1, fig2], dpi=100)
        plt.close(fig1)
        plt.close(fig2)
        img = Image.open(BytesIO(png))
        assert img.height >= 4 * 100  # taller figure (5in) dominates at dpi=100


class TestScrollableImageHtml:
    def test_returns_html_with_matching_dimensions_and_height(self):
        fig = make_fig(2, 3, 'green')
        png = stitch_figures_horizontally([fig])
        plt.close(fig)

        img = Image.open(BytesIO(png))
        html, height = scrollable_image_html(png)

        assert height == img.height
        assert f'width="{img.width}"' in html
        assert f'height="{img.height}"' in html
        assert 'overflow-x:auto' in html
        assert 'base64,' in html
