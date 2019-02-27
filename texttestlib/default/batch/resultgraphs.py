
""" Simple interface to matplotlib """


class MatplotlibError(Exception):
    pass


try:
    import matplotlib
except ImportError:
    raise MatplotlibError("Could not find the Matplotlib module, which must be present for graphs to be produced.")

version = matplotlib.__version__
versionParts = tuple(map(int, version.split(".")[:2]))
if versionParts < (0, 98):
    raise MatplotlibError("Graph generation requires at least matplotlib version 0.98" +
                          ", while version " + version + " is installed.")

matplotlib.use("Agg")  # set backend to one that doesn't need a DISPLAY
import pylab
import logging
import operator
from texttestlib import plugins
from collections import OrderedDict
from functools import reduce


class Graph:
    cms_per_inch = 2.54
    # Initiation of the class with default values

    def __init__(self, title, width, height):
        self.y_label = ''
        self.x_label = ''
        self.plotLabels = []
        self.legendItems = []
        # creating and set size of the graph
        pylab.clf()
        self.fig1 = pylab.figure(1)
        self.fig1.set_figwidth(width / self.cms_per_inch)
        self.fig1.set_figheight(height / self.cms_per_inch)
        self.sub1 = pylab.subplot(111)
        pylab.title(title, fontsize=10, family='monospace')

    def save(self, fn):
        self.finalise_graph()
        self.fig1.savefig(fn, dpi=100)

    def addPlot(self, x_values, y_values, label, *args, **kw):
        self.plotLabels.append(label)
        return self.sub1.plot(x_values, y_values, label=label, *args, **kw)

    def addFilledRegion(self, x_values, old_y_values, y_values, label, color="", *args, **kw):
        self.sub1.set_autoscale_on(False)
        # Add an invisible line, so it can find where to put the legend
        l1, = self.addPlot(x_values, y_values, label, color=color, *args, **kw)
        l1.set_visible(False)
        self.sub1.set_autoscale_on(True)
        for subx, sub_old_y, suby in self.findFillRegions(x_values, old_y_values, y_values):
            if len(subx):
                self.sub1.fill_between(subx, sub_old_y, suby, color=color, *args, **kw)
        self.legendItems.append(pylab.Rectangle((0, 0), 1, 1, fc=color))

    def findFillRegions(self, x_values, old_y_values, y_values):
        lists = []
        lists.append(([], [], []))
        regions = [(i, i + 1) for i in range(len(x_values) - 1)]
        for index1, index2 in regions:
            if old_y_values[index1] == y_values[index1] and old_y_values[index2] == y_values[index2]:
                if len(lists[-1][0]):
                    lists.append(([], [], []))
            else:
                currX, currOldY, currY = lists[-1]
                if len(currX) > 0 and currX[-1] == index1:
                    indices = [index2]
                else:
                    indices = [index1, index2]
                for index in indices:
                    currX.append(x_values[index])
                    currOldY.append(old_y_values[index])
                    currY.append(y_values[index])
        return lists

    def setXticks(self, labelList):
        pylab.xticks(list(range(len(labelList))), labelList)
        pylab.setp(self.sub1.get_xticklabels(), 'rotation', 90, fontsize=7)

    def finalise_graph(self):
        lower = self.sub1.get_ylim()[0]
        if lower < 0:
            self.sub1.set_ylim(ymin=0)  # don't get less than 0, which matplotlib 0.99 does sometimes
        self.sub1.autoscale_view(tight=True, scaley=False)
        leg = self.sub1.legend(self.legendItems, tuple(self.plotLabels), loc='best', shadow=False)
        leg.get_frame().set_alpha(0.5)  # transparent legend box


class PieGraph:
    cms_per_inch = 2.54

    def __init__(self, title, extratitle, size):
        self.fig1 = pylab.figure(1)
        self.fig1.set_figwidth(size / self.cms_per_inch)
        self.fig1.set_figheight(size / self.cms_per_inch)
        self.title = title
        self.extratitle = extratitle

    def pie(self, fracs, colours):
        self.fig1.clf()
        pylab.axes([0, 0, 1, 1])
        explode = []
        tot = sum(fracs)
        for fr in fracs:
            if float(fr)/float(tot) < 0.1:
                explode.append(0.05)
            else:
                explode.append(0)
        dummy, dummy2, texts = pylab.pie(fracs, explode=explode, colors=colours, autopct='%1.1f%%', shadow=True)
        for text in texts:
            text.set_size(8)
        self.fig1.suptitle(self.title, fontsize=10, family='monospace')
        self.fig1.text(0.5, 0, self.extratitle, fontsize=10, family='monospace', horizontalalignment='center')

    def save(self, fn, **kw):
        self.fig1.savefig(fn, dpi=100, **kw)


class GraphGenerator:
    labels = OrderedDict()
    labels["success"] = "Succeeded tests"
    labels["performance"] = "Performance difference"
    labels["faster"] = "Performance faster"
    labels["slower"] = "Performance slower"
    labels["memory"] = "Memory difference"
    labels["smaller"] = "Less Memory"
    labels["larger"] = "More Memory"
    labels["knownbug"] = "Known Issues"
    labels["failure"] = "Failed tests"
    labels["incomplete"] = "Not completed"

    def __init__(self):
        self.diag = logging.getLogger("GenerateWebPages")
        self.diag.info("Generating graphs...")

    def generateGraph(self, fileName, graphTitle, results, colourFinder):
        plugins.log.info("Generating graph at " + fileName + " ...")
        graph = Graph(graphTitle, width=24, height=20)
        self.addAllPlots(graph, results, colourFinder)
        self.addDateLabels(graph, results)
        plugins.ensureDirExistsForFile(fileName)
        graph.save(fileName)

    def getGraphMinimum(self, bottomPlot, topPlot):
        actualMin = min(bottomPlot)
        range = max(max(topPlot) - actualMin, 1)
        targetMin = max(actualMin - range * 2, 0)
        # Round to nearest 10 to avoid a white blob at the bottom
        return (targetMin // 10) * 10

    def addAllPlots(self, graph, results, *args):
        prevYlist = [0] * len(results)
        plotData = OrderedDict()
        for category in list(self.labels.keys()):
            currYlist = [summary.get(category, 0) for _, summary in results]
            if self.hasNonZero(currYlist):
                ylist = [(currYlist[x] + prevYlist[x]) for x in range(len(prevYlist))]
                plotData[category] = prevYlist, ylist
                prevYlist = ylist

        for category in reversed(list(plotData.keys())):
            prevYlist, ylist = plotData[category]
            if not self.hasNonZero(prevYlist):
                # Adjust the bottom of the graph to avoid a huge block of green for large suites
                prevYlist = [self.getGraphMinimum(ylist, list(plotData.values())[-1][-1])] * len(ylist)
            self.addPlot(prevYlist, ylist, graph, category=category, *args)

    def hasNonZero(self, numbers):
        return reduce(operator.or_, numbers, False)

    def addPlot(self, prevYlist, ylist, graph, colourFinder, category=""):
        colour = colourFinder.find(category + "_bg")
        label = self.labels[category]
        self.diag.info("Creating plot '" + label + "', coloured " + colour)
        xlist = list(range(len(ylist)))
        self.diag.info("Data to plot = " + repr(ylist))
        graph.addFilledRegion(xlist, prevYlist, ylist, label=label, linewidth=2, linestyle="-", color=colour)

    def addDateLabels(self, graph, results):
        xticks = []
        # Create list of x ticks
        numresults = len(results)
        # Interval between labels (10 labels in total, use '' between the labels)
        interval = max(numresults / 10, 1)
        for i, (tag, _) in enumerate(results):
            tick = tag if i % interval == 0 else ""
            xticks.append(tick)
        graph.setXticks(xticks)
