var CommentServer = CommentServer || "comment.php";
var CommentListHtml = CommentListHtml || "commentlist.html";

//
// Section representing the comments stored in extenal file.
//

var replace = function(str, replacePairs)
{
    $(replacePairs).each(function(i,pair) {
	    str = str.replace(pair[0],pair[1]);
	});
    return str;
};

var myEncode = function(str) {
    return replace(str,[
		[/\\/g,"\\\\"],
		[/\"/g,"\\\""],
		[/\t/g,"\\t"],
		[/@/g,"\@@"],
		[/\n/g,"\\n"]]);
};

var myDecode = function(str) {
    return replace(str,[
               [/\\\"/g,"\""],
               [/\\t/g,"\t"],
               [/\@@/g,"@"],
               [/\\n/g,"<br>"],
               [/\\\\/g,"\\"]]);
};


// Entry - a Representing a row in the comment "database"
var Entry = function(comment, author, tests) {
    this.id = (new Date()).valueOf(); // unique enough?
    this.tests = tests;
    this.author = author;
    this.comment = comment;
};
Entry.prototype.serialize = function() {
    return this.id + ";" + 
        this.tests.serialize() + ";" +
        this.author.serialize() + ";" +
        this.comment.serialize();
};
Entry.prototype.deSerialize = function(str) {
    var strs = str.split(";");
    this.author = new Author("");
    this.comment = new Comment("");
    this.tests = new Tests();

    this.id = strs[0];
    this.tests.deSerialize(strs[1]);
    this.author.deSerialize(strs[2]);
    this.comment.deSerialize(strs.slice(3,strs.length).join(";"));
    return this;
};

// Author
var Author = function(text) {
    this.author = text;
    this.time = null;
};
Author.prototype.serialize = function() {
    var now = new Date();
    s = now.toString().substring(4,21).split(" ")
    return this.author + ","+s[1]+" "+s[0]+" "+s[2]+" "+s[3];
};
Author.prototype.deSerialize = function(str) {
    var strs = str.split(",");
    this.author = strs[0];
    if (strs.length > 1)
	this.time = strs[1];
    else
	this.time = null;
};
Author.prototype.toString = function() {
    var str = "By " + this.author;
    if (this.time)
	str += ", " + this.time;
    return str;
};

// Comment
var Comment = function(text) {
    this.text = text;
};
Comment.prototype.serialize = function() {
    return myEncode(this.text);
};
Comment.prototype.deSerialize = function(str) {
    this.text = myDecode(str);
};
Comment.prototype.toString = function() {
    var text = replace(this.text,[
		[/</g,"&lt;"],
		[/>/g,"&gt;"],
		[/\n/g,"<br>"]]);
    var jiraText = text.replace(/\[([^@]*)@[Jj][Ii][Rr][Aa]\]/g,
				"<a href='https://jira.jeppesensystems.com/browse/$1'>JIRA Issue $1</a>");
    return jiraText;
};

// Tests
var Tests = function() {
    this.tests = {};
};
Tests.prototype.add = function(test, date)
{
    if (!this.tests.hasOwnProperty(date))
	this.tests[date] = [];
    this.tests[date].push(test);
};
Tests.prototype.get = function(date)
{
    return this.tests[date];
};
Tests.prototype.getDates = function()
{
    var dates = [];
    for (date in this.tests)
	if (this.tests.hasOwnProperty(date))
	    dates.push(date);
    return dates;
};
Tests.prototype.serialize = function() {
    var dateTests = [];
    var this_ = this;
    $(this.getDates()).each(function(i,date) {
	var testKeys = [];
	$(this_.get(date)).each(function(j,test){testKeys.push(test.key)});
	dateTests.push(date + "=" + testKeys.join(","));
    });
    return myEncode(dateTests.join("&"));
    // e.g. date1=test1,test2,test3&date2=test4,test5
};
Tests.prototype.deSerialize = function(str) {
    str = myDecode(str);
    var dateTestsList = str.split("&");
    var this_ = this;
    $(dateTestsList).each(function(i, dateTests) {
	var strs = dateTests.split("=");
        var date = strs[0];
        var tests = strs.slice(1,strs.length).join("=");
	var strs2 = tests.split(",");
	this_.tests[date] = [];
	$(strs2).each(function(i,test){ 
	    var ts = test.split("/");
	    if (ts.length==3)
		this_.tests[date].push(new Test(ts[0] + ts[2] + ts[1], ts[2]));
	});
    });
};

// Test 
//   - 'testKeyRaw' is the existing key for this test
//   - 'testNameRaw' may have newline chars in beginning/end
var Test = function(testKeyRaw, testNameRaw) {
    var testNameOneLine = testNameRaw.replace(/\n/g,"");
    testVersion = testKeyRaw.replace(testNameOneLine,"/");
    var prettyTestKey = testVersion + "/" + testNameOneLine;
    
    this.name = testNameOneLine;
    this.rawKey = testKeyRaw;
    this.key = prettyTestKey;
    this.version = testVersion;
};

//
// Tooltip stuff
//

var createTooltip = function(height, width)
{
    tooltip = $("<div id='tooltip'></div>");
    tooltip.css({'position':'absolute','z-index':'10'});
    var innerTooltip = $("<div class='innerTooltip'></div>");
    var authorDiv = $("<div name='author'></div>").css('color','#888888');
    var commentDiv = $("<div name='comment'></div>");
    commentDiv.css({'width':width + 'px',
		'height':height+'px'});
    innerTooltip.append(commentDiv);
    commentDiv.css({'overflow-y':'auto',
		'overflow-h':'hidden'});
    innerTooltip.append(authorDiv);
    tooltip.append(innerTooltip);
    tooltip.hide();

    tooltip.hover(function(e) { 
	    clearTimeout($(this).prop('timerId'));
	    $(this).show();
	}, 
	function(e) { 
	    var timerId = setTimeout(function(){ 
		    $("#tooltip").hide(); 
		}, 250);
	    $(this).prop('timerId',timerId);
	});
    return tooltip;
};

var showToolTip = function(event, commentStr, authorStr, tdEventSource)
{
    var tooltipHeight = 150;
    var tooltipWidth = 250;

    var tooltip = $("#tooltip");
    if (tooltip.size() == 0)
    {
	tooltip = createTooltip(tooltipHeight, tooltipWidth);
	$(document.body).append(tooltip);
    }

    tooltip.find("[name='author']").text(authorStr);
    tooltip.find("[name='comment']").html(commentStr);

    var mouseXinDoc = event.clientX + $(window).scrollLeft();
    var mouseYinDoc = event.clientY + $(window).scrollTop();
    var tooltipX = mouseXinDoc - ((event.clientX > $(window).width()/2) ? (tooltipWidth+10) : 0);
    var tooltipY = mouseYinDoc - ((event.clientY > $(window).height()/2) ? (tooltipHeight+25) : 0);

    tooltip.css({'top': tooltipY + "px",
		'left': tooltipX + "px"});
    tooltip.trigger('mouseover');
};

var hideToolTip = function()
{
    $("#tooltip").trigger('mouseout');
};

var updateComment = function(comment, author, td, commentNum)
{
    if (td.find("[name='"+commentNum+"']").length == 0)
    {
	var div = $("<div></div>").addClass('commentMarker');
	div.attr('name', commentNum);
        div.attr('id', 'commentMarker' + commentNum);
	div.html(commentNum);
	
	div.hover(function(e) { 
		$(this).addClass('commentMarkerHover');
		showToolTip(e, comment.toString(), 
			    author.toString(), td.get(0));
	    }, 
	    function(e) { 
		$(this).removeClass('commentMarkerHover');
		hideToolTip();
	    });
	
	td.append(div);
    }
};

var updateComments = function(entries, grid)
{
    var commentsPerDate = {};
    $(entries).each(function(i, entry) {
	// foreach entry

	$(entry.tests.getDates()).each(function(j,date) {
	    // foreach date

	    if (!commentsPerDate[date])
		commentsPerDate[date] = 0;
	    commentsPerDate[date]++;

	    $(entry.tests.get(date)).each(function(k, test) {

		// foreach test
		var rowHeader = $("a[name='"+test.rawKey+"']").parent();

		if (rowHeader.size() > 0)
		{
		    var column = grid.getCol(rowHeader, date);
		    if (column > -1)
		    {
			var td = $(rowHeader.siblings().get(column));
			updateComment(entry.comment, 
				      entry.author, 
				      td, 
				      commentsPerDate[date]);
		    }
		}
	    });
	});
    });
};

var getEntries = function(dates)
{
    var encodedDates = [];
    $(dates).each(function(i, date) {
	    encodedDates.push(myEncode(date));
	});
    var entriesRaw = null;

    $.ajax({url: CommentServer, 
	    async: false,
	    type: "POST", 
	    data: {'method' : "get",
		   'dates'  : encodedDates},
	    success: function(result){if (result['err']) alert(result['err']); else {entriesRaw = result;}},
	    error: function(a,b,c){alert("getEntries error!\n\n" + a + "\n" + b + "\n" + c);},
	    dataType: "json"
    });		

    var entries = [];
    $(entriesRaw).each(function(i,entryRaw) { 
	if (entryRaw.length > 0) {
	    var entry = new Entry();
	    entries.push(entry.deSerialize(entryRaw));
	}
    });
    return entries;
};

var timeStampedAuthor = function(author)
{
    var now = new Date();
    s = now.toString().substring(4,21).split(" ")
    return author + ", "+s[1]+" "+s[0]+" "+s[2]+" "+s[3];
};

var postEntry = function(entry)
{
    $.ajax({url: CommentServer, 
	    async: false,
	    type: "POST", 
	    data: {'method' : "set",
		   'entry'   : entry.serialize()}, 
	    success: function(result){if (result['err']) alert(result['err']);},
	    error: function(a,b,c){alert("postEntry error!\n\n" + c);},
	    dataType: "json"
    });		
};

var deleteEntry = function(entry)
{
    $.ajax({url: CommentServer, 
	    async: false,
	    type: "POST", 
	    data: {'method' : "delete",
		   'id'   : entry.id}, 
	    success: function(result){if (result['err']) alert(result['err']);},
	    error: function(a,b,c){alert("deleteEntry error!\n\n" + c);},
	    dataType: "json"
    });		
};

var postComment = function(selection, commentStr, authorStr, grid)
{
    var getSelectedTests = function(selection)
    {
	var tests = new Tests();
	var elems = selection.get();
	$(elems).each(function() {
	    var tr = $(this).parent("tr");
	    var name = tr.find("td").first().text();
	    var testkey = tr.find("a").first().attr('name');
	    var testDate = grid.getDate($(this));
			
	    var test = new Test(testkey, name);
	    tests.add(test, testDate);
	});
	return tests;
    };

    var tests = getSelectedTests(selection);
    var comment = new Comment(commentStr);
    var author = new Author(authorStr);
    var entry = new Entry(comment, author, tests);
    postEntry(entry);
    selection.clear();
    selection.notify();
};

var appendCommentLinks = function(entries)
{
    var countComments = function(entries, date)
    {
	var count = 0;
	$(entries).each(function(i, entry) {
		var tests = entry.tests.get(date);
		if (tests)
		    count += 1;
	    });
	return count;
    };

    $( $.find("th:contains('Test')") ).siblings().each( function() { 
	$(this).find("[name='AllLink']").remove(); // Remove existing links

	var date = $(this).text().split("\n")[0];
	var link = $("<div id='allLink" + date + "' name='AllLink'>All ("+countComments(entries, date)+")</div>");
	link.click(function(){window.location.href = CommentListHtml + '?'+date});
	link.css({'float':'right', 
		  'background-color':'#FFFFCC',
		  'cursor':'default'});
	$(this).append(link);
    });
};

// Selection
var Selection = function(callback) {
    this.callback = callback;
    this.lookupTable = {};
};
Selection.prototype.notify = function() {
    this.callback(this);
};
Selection.prototype.add = function(testElem) {
    var tag = this._tag(testElem);
    if (!this.lookupTable[tag])
    {
	this.lookupTable[tag] = testElem;
	this._mark(testElem);
    }
};
Selection.prototype.remove = function(testElem) {
    delete this.lookupTable[this._tag(testElem)];
    this._unmark(testElem);
};
Selection.prototype.contains = function(testElem) {
    return this.lookupTable[this._tag(testElem)];
};
Selection.prototype.get = function() {
    var elems = [];
    for (key in this.lookupTable)
	if (this.lookupTable.hasOwnProperty(key))
	    elems.push(this.lookupTable[key]);
    return elems;
};
Selection.prototype.clear = function() {
    var elems = this.get();
    var s = this;
    $(elems).each(function(i,el){ s.remove(el); });
};
Selection.prototype._tag = function(testElem) {
    return testElem.get(0)._tag;
};
Selection.prototype._mark = function(testElem) {
    var el = testElem.get(0);
    if (!el._ismarked)
    {			
	el._origcolor = testElem.css('background-color');
	var origRGB = el._origcolor.replace(/[^0-9,]/g, "").split(",");
	var markedRGB = [Math.round(origRGB[0]/1.5), 
			 Math.round(origRGB[1]/1.5), 
			 Math.round((255+parseInt(origRGB[2]))/2)];
	testElem.css('background-color', 
		     'rgb('+markedRGB[0]+','+markedRGB[1]+','+markedRGB[2]+')');
	el._ismarked = true;
    }
};
Selection.prototype._unmark = function(testElem) {
    var el = testElem.get(0);
    if (el._ismarked)
    {
	testElem.css('background-color', el._origcolor);
	el._ismarked = false;
    }
};
	
var getAuthorCookie = function()
{
    var authorStr = "";
    var pairs = document.cookie.split(";");
    $(pairs).each(function(i,pairStr) {
	var pair = pairStr.split("=");
	if (pair[0].search("author") > -1)
	    authorStr = unescape(pair[1]);
    });
    return authorStr;
};
	
var setAuthorCookie = function(authorStr)
{
    var setAuthorCookieImpl = function(str, year)
    {
	document.cookie = "author=" + escape(authorStr) + ";expires=" + (new Date(year,0)) + ";path=/"
    };
    setAuthorCookieImpl(authorStr, 2000);  // expires year 2000 (reset)
    setAuthorCookieImpl(authorStr, 4000);  // expires year 4000
    return authorStr;
};

var validateAuthorField = function(auth, commentButton)
{
    if (auth.val() == "")
	commentButton.attr('disabled','disabled');
    else
	commentButton.removeAttr('disabled');
};

var CommentUILogic = function() {};
CommentUILogic.prototype.onComment = function(handler) {
    this.onCommentHandler = handler;
};
CommentUILogic.prototype.onCancel = function(handler) {
    this.onCancelHandler = handler;
};
CommentUILogic.prototype.setAuthorColor = function(color) {
    this.authorColor = color;
};
CommentUILogic.prototype.setComment = function(comment) {
    var textarea = this.ui.find("textarea");
    textarea.val(comment);
    textarea.attr('rows', Math.min(10, comment.split("\n").length));
};

var appendCommentUI = function(logic, parent)
{
    commentTable = $("<table id=commentTable></table>").css('width','100%');
    var comment = $("<textarea id=commentField></textarea>").css('width','100%');
    var commentButton = $("<button id=commentButton>Comment</button>").width(200);
    var authorField = $("<input id=authorField type=text value='" + getAuthorCookie() + "'></input>");
    var cancelButton = $("<button id=cancelButton>Cancel</button>");

    authorField.keyup(function(){validateAuthorField($(this), commentButton)});
    validateAuthorField(authorField, commentButton);
    commentButton.click(function() { 
        logic.onCommentHandler(comment.val(), setAuthorCookie(authorField.val())); 
    });
    cancelButton.click(function() { 
	logic.onCancelHandler();
    });
    var tr = $("<tr></tr>");
    var td = $("<td></td>");
    commentTable.append(tr.clone().append(td.clone().attr('colspan',4).css('padding-right','15px').append(comment)));
    tr.append(td.clone().append($("<span>Author</span>").css({
	'color':logic.authorColor,
	'font-size':'12px'})));
    tr.append(td.clone().append(authorField));
    tr.append(td.clone().append(commentButton));
    tr.append(td.css('width','100%').append(cancelButton));
    commentTable.append(tr);
    parent.append(commentTable);
    comment.focus();
    logic.ui = commentTable;
};


// ColumnDateDefinition
var ColumnDateDefinition = function(rowElem) {
    this.dateList = []
    this.colToDateDict = {};

    var this_ = this;
    // Collect dates in row
    rowElem.find("th:contains('Test')").siblings().each( function() { 
	this_.dateList.push($(this).text().split("\n")[0]);
    });
    // Create mapping from date to column
    $(this.dateList).each(function(i,date) {
	this_.colToDateDict[date] = i;
    });
};
ColumnDateDefinition.prototype.getCol = function(date) {
    return this.colToDateDict[date];
};
ColumnDateDefinition.prototype.getDate = function(col) {
    return this.dateList[col];
};
ColumnDateDefinition.prototype.getDates = function() {
    return this.dateList;
};

// Row
var Row = function(rowElem, colDateDef) { 
    this.colDateDef = colDateDef;
    this.rowHeader = rowElem.find("td").first();
    this.elems = [];
    var this_ = this;

    $(this.rowHeader).siblings().each(function(i, td) {
	    this_.elems.push($(td));
	});
};
Row.prototype.size = function() {
    return this.elems.length;
};
Row.prototype.getHeader = function() {
    return this.rowHeader;
};
Row.prototype.get = function(index) {
    return this.elems[index];
};
    
// Grid
var Grid = function() {
    this.rows = [];
    this.coordTable = {};

    this.elemCount = 0;
};
Grid.prototype.registerRow = function(row) {
    this.rows.push(row);
    this._tagElem(row.getHeader(), -1);
    for (var i = 0; i < row.size(); ++i)
	this._tagElem(row.get(i), i);
};
Grid.prototype._tagElem = function(elem, colNum) {
    elem.get(0)._tag = this.elemCount++;
    this.coordTable[elem.get(0)._tag] = {row:this.rows.length-1, 
					 col:colNum};
};
Grid.prototype.getCoord = function(testElem) {
    return this.coordTable[testElem.get(0)._tag];
};
Grid.prototype.getDate = function(testElem) {
    var coord = this.getCoord(testElem);
    var row = this.rows[coord.row];
    return row.colDateDef.getDate(coord.col);
};
Grid.prototype.getCol = function(rowHeaderElem, date) {
    var coord = this.getCoord(rowHeaderElem);
    var row = this.rows[coord.row];
    return row.colDateDef.getCol(date);
};	
Grid.prototype.getElem = function(coord) {
    return this.rows[coord.row].get(coord.col);
};
Grid.prototype.isVisible = function(row) {
    return (this.rows[row].get(0).is(':visible'));
};

// GridBuilder
var GridBuilder = function() {
    this.grid = new Grid();
    this.allDates = {};
    this.currentColDateDef = null;
};
GridBuilder.prototype.setColDateDefinition = function(rowElem) {
    this.currentColDateDef = new ColumnDateDefinition(rowElem);
    var dates = this.currentColDateDef.getDates();
    for (var i = 0; i < dates.length; i++)
	this.allDates[dates[i]] = 1; // dummy value
};
GridBuilder.prototype.addRow = function(rowElem) {
    var row = new Row(rowElem, this.currentColDateDef);
    this.grid.registerRow(row);
};
GridBuilder.prototype.getGrid = function() {
    return this.grid;
};
GridBuilder.prototype.getAllDates = function() {
    var dates = [];
    for (date in this.allDates)
	if (this.allDates.hasOwnProperty(date))
	    dates.push(date);
    return dates;
};	

// SelectionBuilder
var SelectionBuilder = function(selection, grid) {
    this.selection = selection;
    this.grid = grid;
};
SelectionBuilder.prototype.beginSelection = function(testElem) {
    if (this.rectStart) // shouldn't happen normally...
    {
	this.endSelection();
	return;
    }
    
    if (this.selection.contains(testElem))
    {
	this.selection.remove(testElem);
	this.selection.notify();
	return;
    }		
    this.rectStart = this.grid.getCoord(testElem);
    this.rectEnd = this.rectStart;
    this.currentSelection = new Selection();
    this._select(testElem, true);
};
SelectionBuilder.prototype.endSelection = function() {
    if (this.rectStart)
    {
	this.rectStart = null;
	var elems = this.currentSelection.get();
	var selection = this.selection;
	$(elems).each(function(i,el){ selection.add(el) });
	delete this.currentSelection;
	this.selection.notify();
    }
};
SelectionBuilder.prototype.select = function(testElem) {
    if (this.rectStart) 
    {
	var s = this.rectStart;               // start
	var e = this.rectEnd;                 // end
	var c = this.grid.getCoord(testElem); // current
	
	for (var row = Math.min(s.row, e.row, c.row); 
	     row <= Math.max(s.row, e.row, c.row); row++)
	{
	    if (!this.grid.isVisible(row))
		continue;
	    for (var col = Math.min(s.col, e.col, c.col); 
		 col <= Math.max(s.col, e.col, c.col); col++)
	    {
		var inPrevRect = (row >= Math.min(s.row, e.row)) && (row <= Math.max(s.row, e.row)) &&
		    (col >= Math.min(s.col, e.col)) && (col <= Math.max(s.col, e.col));
		var inCurrRect = (row >= Math.min(s.row, c.row)) && (row <= Math.max(s.row, c.row)) &&
		    (col >= Math.min(s.col, c.col)) && (col <= Math.max(s.col, c.col));
		if (inPrevRect && !inCurrRect)
		    this._select(this.grid.getElem({'row':row, 'col':col}), false);
		else if (!inPrevRect && inCurrRect)
		    this._select(this.grid.getElem({'row':row, 'col':col}), true);
	    }
	}
	this.rectEnd = c;
    }
};
SelectionBuilder.prototype._select = function(testElem, yeah) {
    if (yeah)
    {
	if (!this.selection.contains(testElem))
	{
	    this.currentSelection.add(testElem);
	}
    }
    else
    {
	if (this.currentSelection.contains(testElem))
	    this.currentSelection.remove(testElem);
    }
};
		
var selectionChangedImpl = function(selection, grid, allDates) 
{
    var commentTable = $("#commentTable");
    // Add comment UI if it doesn't exist.
    if (commentTable.length == 0) 
    {
	var logic = new CommentUILogic();
	logic.selection = selection;
	logic.setAuthorColor('white');
	logic.onComment(function(commentStr, authorStr) {
	    postComment(this.selection, commentStr, authorStr, grid); 
	    var entries = getEntries(allDates);
	    updateComments(entries, grid);
	    appendCommentLinks(entries);
	});
	logic.onCancel(function() { 
	    selection.clear(); 
	    selection.notify(); 
	});
	
	appendCommentUI(logic,$("#colorbar"));
    }
		
    var elems = selection.get();
    if (elems.length == 0) 
    {
	commentTable.hide();
	$("#colorbar").triggerHandler('mouseout');
    }
    else 
    {
	$("#colorbar").triggerHandler('mouseover');
	$("#commentButton").text("Comment " + elems.length + " tests");
	commentTable.show();			
	commentTable.find("textarea").focus();
    }
};
		
var setupCss = function() {
    var CssClass = function(name) {
	this.name = name;
	this.styles = [];
    };
    CssClass.prototype.add = function(key, value) {
	this.styles.push(key+":"+value);
    };
    CssClass.prototype.get = function() {
	var style = $("<style type='text/css'></style>");
	var text = "." + this.name + "\n{" + this.styles.join(";\n") + "}";
	return style.text(text);
    };
    
    var commentMarker = new CssClass("commentMarker");
    commentMarker.add("position","relative");
    commentMarker.add("padding","1px");
    commentMarker.add("margin","1px");
    commentMarker.add("background-color","#FFFFCC");
    commentMarker.add("font-size",'10px');
    commentMarker.add("float", "right");
    commentMarker.add("cursor", "default");
    commentMarker.add('-moz-border-radius', '3px');
    commentMarker.add('border-radius', '3px');
    commentMarker.add('background-image', 
		      '-moz-linear-gradient(top, #FFFFCC, #DDDD88)');
    
    var commentMarkerHover = new CssClass("commentMarkerHover");
    commentMarkerHover.add('background-image', 
			   '-moz-linear-gradient(top, #E0E088, #888800)');

    var innerTooltip = new CssClass("innerTooltip");
    innerTooltip.add('position', 'relative');
    innerTooltip.add('background-color', '#FFFFFF');
    innerTooltip.add('padding', '3px');
    innerTooltip.add('border', '1px solid gray');
    innerTooltip.add('font-size', '12px');
    innerTooltip.add('-moz-border-radius', '8px');
    innerTooltip.add('border-radius', '8px');

    $("head").append(commentMarker.get());
    $("head").append(commentMarkerHover.get());
    $("head").append(innerTooltip.get());
};

var myAlert = function(message) {
    var div = $("<div/>").css({'background-color': "#BB0000",
			       'color': "#FFFFFF",
	                       'position': "fixed",
	                       'font-size': "15px",
			       'padding': "5px",
			       'top': "0px",
			       'right': "0px" });
    div.text(message);
    $(document.body).append(div);
    div.delay(2000).fadeOut('slow');
};

// setup
var setup = function() {
    // Return if no filter toolbar is available
    if ($("#colorbar").length == 0)
	return;
    
    if (window.location.protocol.search("file") > -1) {
	myAlert("Comment plugin only works with 'http:' protocol!");
	return;
    }

    if (navigator.appName.search("xplorer") > -1) {
	myAlert("Internet Explorer not supported by comment plugin!");
	return;
    }
	

    setupCss();
    var gridBuilder = new GridBuilder();
    
    var selectionChanged = function(selection) { 
	selectionChangedImpl(selection, 
			     gridBuilder.getGrid(), 
			     gridBuilder.getAllDates()) 
    };
    var selectionBuilder = new SelectionBuilder(new Selection(selectionChanged), 
						gridBuilder.getGrid());

    // Parse all rows
    $(document.body).find("tr").each(function() {	
	    
        var setupMouseEvents = function(testElem) {
	    testElem.mousedown(function(e) {
		if (e.target == testElem.get(0))
		{
		    e.preventDefault(); // Avoid marking
		    selectionBuilder.beginSelection($(this));	
		    
		    // some capture magic
		    var mouseUp = function() {
			$(document.body).unbind("losecapture");
			if (document.body.releaseCapture)
			    document.body.releaseCapture();
			selectionBuilder.endSelection() 
		    };								
		    $(document.body).bind("losecapture", mouseUp);
		    $(document.body).mouseup(mouseUp);
		    
		    if (document.body.setCapture)
			document.body.setCapture();
		}
	    });		
	    testElem.mouseover(function(event) {
		selectionBuilder.select($(this));
	    });
	};
	
	var isTestHeader = function(row) {
	    return (row.find("th").first().text() == "Test");
	};
	
	if (isTestRow($(this)[0]))
	{
	    $(this).find("td").first().siblings().each(function() {
		    setupMouseEvents($(this));
	    });
	    gridBuilder.addRow($(this));
	}
	else if (isTestHeader($(this)))
	    gridBuilder.setColDateDefinition($(this));	
	});
    
    var entries = getEntries(gridBuilder.getAllDates());
    updateComments(entries, gridBuilder.getGrid());
    appendCommentLinks(entries);
};

$(document).ready(setup);




