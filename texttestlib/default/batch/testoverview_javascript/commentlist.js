
var node = function(content, bgcolor, position)
{
	var d = $("<div></div>").css({
		'position': position || 'relative',
		'padding':'4px',
		'background-color':bgcolor}).html(content || "");
	return d;
};

var createDateNode = function(dateString, hasComments)
{
	var allTests = function(node, expand)
	{
		var tests = node.find("[name='tests']");
		if (expand)
			tests.show("fast");
		else
			tests.hide("fast");
	};

	var testDate = createTestDate( dateString );
	var day = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][testDate.date().getDay()];
	var isFriday = day == 'Friday';
	
	var dayElem = $("<div/>").css({"float" : 'right', "font-size" : "12px", 'color':"#888888"}).text(day);
	var wrap = $("<div/>").append( dayElem );
	//wrap.append(dayElem);
	var n = node(dateString + wrap.html());
	n.css('font-size','24px');
	
	if (hasComments)
	{
		var expand = $("<button>+</button>").css('float','right');
		var collapse = $("<button>-</button>").css('float','right');
		expand.click(function(){ allTests($(this).parent().parent(), true); });
		collapse.click(function(){ allTests($(this).parent().parent(), false); });
		
		/* We can live without these buttons...?
		n.append(expand);
		n.append(collapse);	
		*/
	}

	var ret = node(n); //, isFriday?"#F0D0D0":"#E0E0E0");
        var gradFrom = isFriday ? "#F0D0D0" : "#E0E0E0";
        var gradTo = isFriday ? "#E0B0B0" : "#C0C0C0";

        ret.css('background',
                '-moz-linear-gradient(top, '+gradFrom+', '+gradTo+')');
        ret.css('background',
                '-webkit-gradient(linear, left top, left bottom, from('+gradFrom+'), to('+gradTo+'))');
        ret.addClass("rounded");
        return ret;
};

var createVersionNode = function(version)
{
	return node(node(version).css({'font-weight':'bold','padding':'0px'}));
};

var createCommentNode = function(comment)
{
	var n = node(comment.toString(), '#F8F8F8');
        n.find("a").click(function(e){ e.stopPropagation(); });
        n.addClass("rounded-top");
        n.css('font-size','14px');
        return n;
};

var createAuthorNode = function(entry, nodeId)
{
        var n = node(entry.author.toString(), '#F0F0F0');
        n.addClass("rounded-bottom");
        n.css({'color':'#888888','font-size':'12px'});

        appendCommentActions(n, entry, nodeId);
        
        return n;
};

var appendTests = function(parent, sortedTests)
{
	var prevVersion = "";
	var versionNode = null;
	$(sortedTests).each(function(i,test) {
		var t = test.key.split("/");
		var version = t[0] + (t[1]=="" ? "" : "." + t[1]);
		if (version != prevVersion)
		{
			parent.append(versionNode);
			versionNode = createVersionNode(version);
			prevVersion = version;
		}
		versionNode.append(node(t[2]));
	});
        if (versionNode)
            parent.append(versionNode.clone());
};

var createCommentTitle = function(title)
{
    return node(title).css({'font-size':'12px',
                            'color':'#888888'});
};

var appendCommAuth = function(parent, entry, nodeId)
{
       	parent.append(createCommentNode(entry.comment), 
                      createAuthorNode(entry, nodeId));	
};

var createActionButton = function(text)
{
    var action = $("<div>&nbsp;" + text + "&nbsp;</div>");
    action.css({'float':'right',
        'cursor':'default'});
    action.hover(
           function(){ $(this).css('background-color','rgb(200,200,200)'); },
           function(){ $(this).css('background-color',''); });
    action.addClass('rounded');
	return action;
};

var updateComment = function(id, newEntry)
{
	$.ajax({url: CommentServer, 
	async: false,
	type: "POST", 
	data: {'method' : "update",
		   'id' : id,
		   'newentry' : newEntry.serialize()}, 
	success:function(result){if (result['err']) alert(result['err']);},
	error:function(a,b,c){alert("Oops!\n\n" + c);},
	dataType: "json"
   });		
};

var appendCommentActions = function(authorNode, entry, nodeId)
{
	// Delete
    var deleteAction = createActionButton("x");
    deleteAction.attr('id', nodeId + "Delete");
    deleteAction.click(function() {
      if (confirm("Are you sure you want to delete this comment?"))
      {
        deleteEntry(entry);
        $(entry.tests.getDates()).each(function(i, date) {
            refresh(date);
        });
      }
    });
    deleteAction.attr('title','Delete comment');
	
	// Edit
	var editAction = createActionButton("...");
        editAction.attr('title','Edit comment');
        editAction.attr('id', nodeId + "Edit");
	editAction.click(function() {
	        var commentContainer = authorNode.parents().filter("[name='commentContainer']");
			commentContainer.children().hide();
			
		    var logic = new CommentUILogic();
			appendCommentUI(logic, commentContainer);
			logic.setComment(entry.comment.text + 
                                         "\n-- " + entry.author.toString() + 
                                         "\n\n");
		    logic.onComment(function(commentStr, authorStr) {
				var newEntry = new Entry(new Comment(commentStr), new Author(authorStr), entry.tests);
				updateComment(entry.id, newEntry); 
				$(entry.tests.getDates()).each(function(i, date) {
					refresh(date);
				});
		    });
		    logic.onCancel(function() { 
				logic.ui.remove();
				commentContainer.children().show();
		    });

	});
	
    authorNode.append(deleteAction);
	authorNode.append(editAction);
};

var appendCommAuthTests = function(parent, entry, date, nodeid)
{
	var commentNode = createCommentNode(entry.comment);
        var authorNode = createAuthorNode(entry, nodeid);
	var testsNode = node('','#FFFFCC').css('font-size','12px').attr('name','tests').hide();
      	parent.append(commentNode, testsNode, authorNode);
        commentNode.hover(function() { $(this).css('background-color','#DDDDFF') },
                  function() { $(this).css('background-color','#F8F8F8') });
        commentNode.click(function() { 
		if (testsNode.is(':visible'))
			testsNode.hide("fast");
		else
			testsNode.show("fast");
	});

        appendTests(testsNode, entry.tests.get(date).sort());
};

var makeJQselectFriendly = function(str) {
    return str.replace(/[\(\)\.\n]/g,"")
};

var refresh = function(date)
{
    var newSummary = createSummary(date, getEntries([date]));
    $("[name='"+ makeJQselectFriendly(date) +"']").replaceWith(newSummary);
};

var appendCommentPoster = function(parent, date)
{
  // Add Comment button
  var addComment = $("<button id='addComment" + date + "'>Add comment</button>");

  // Comment UI
  var logic = new CommentUILogic();
  logic.setAuthorColor('black');
  logic.onComment(function(commentStr, authorStr) {
    var tests = new Tests();
    tests.tests = {};
    tests.tests[date] = [];
    var entry = new Entry(new Comment(commentStr),
                          new Author(authorStr), tests);
    postEntry(entry);
    refresh(date);
  });
  logic.onCancel(function() {
    logic.ui.hide();
    addComment.show();
  });

  addComment.click(function() {
    $(this).hide();
    logic.ui.show();
    logic.ui.find("textarea").focus();
  });

  parent.append(addComment);
  appendCommentUI(logic, parent);
  logic.ui.hide();
};

var createSummary = function(dateString, entries)
{
	var hasNoComments = entries.length > 0;
	var dateNode = createDateNode(dateString, false, hasNoComments);

        var entriesWithTests = [];
        var entriesWithoutTests = [];
	$(entries).each(function(i,entry) {		
                var tests = entry.tests.get(dateString);
                if (tests && tests.length > 0) 
                       entriesWithTests.push(entry);
                else if (tests)
                       entriesWithoutTests.push(entry);

                // otherwise, the entry contains no comments for this date
	});
	
	$(entriesWithoutTests).each(function(i,entry) {		
		if (i==0)
		  dateNode.append(createCommentTitle("General comments"));
		var commentContainer = node().css('padding-left','12px').attr('name','commentContainer');
		var wrap = node().css('padding','0px');
		dateNode.append(commentContainer.append(wrap));
		appendCommAuth(wrap, entry, "generalComment" + (i+1).toString() + "_" + dateString);		
	});
	$(entriesWithTests).each(function(i,entry) {		
		if (i==0)
		  dateNode.append(createCommentTitle("Comments on tests"));
		var commentContainer = node().css('padding-left','12px').attr('name','commentContainer');
		var wrap = node().css('padding','0px');
		dateNode.append(commentContainer.append(wrap));
		appendCommAuthTests(wrap, entry, dateString, "testComment"  + (i+1).toString() + "_" + dateString);
	});

        var wrap = node();
        dateNode.append(wrap);

        
        appendCommentPoster(wrap, dateString);
	
	return dateNode.attr('name', makeJQselectFriendly(dateString));
};

var loadSummary = function(testDate)
{
      var dateString = testDate.getString();
      var entries = getEntries([dateString]);
      var dateStringSet = {};
      var dateStrings = [];

      // Get all comments for a particular date (dateString).
      // For multiple builds (typically) per date
      // all comments for all builds should be presented.
      // When the dateStrings list is longer than one, the
      // elements are strings with (typically) 'time of day' added.

      for (var i = 0; i < entries.length; i++) {
	  var dates = entries[i].tests.getDates();
	  for (var j = 0; j < dates.length; j++) {
              var date = dates[j];
	      if (dateStringSet[date] == undefined &&
                  date.search(dateString) > -1) {
                  dateStringSet[date] = 1; // dummy
                  dateStrings.push(date);
              }
          }
      } 

      dateStrings.sort().reverse();
	  
	  return {dateStrings: dateStrings,
	          entries:     entries};
};

var appendSummary = function(container, dateStrings, entries) 
{ 
      for (var i = 0; i < dateStrings.length; i++) {
		  var summary = createSummary(dateStrings[i], entries);
		  var table = $("<table><table>");
		  var row = $("<tr></tr>");
		  var cell = $("<td></td>");
		  var minwidther = node().css('width','350px');
		  table.append(row);
		  row.append(cell);
		  cell.append(summary);
		  cell.append(minwidther);
		  container.append(table);
      }
};

var padZeroFirst = function(number) {
      var str = ("0" + number);
      return str.substring(str.length-2, str.length);
};

var TestDate_v1 = function(dateString) {
      // format:  07Jan2012

      this.month_to_num = {Jan:0,Feb:1,Mar:2,Apr:3,May:4,Jun:5,Jul:6,Aug:7,Sep:8,Oct:9,Nov:10,Dec:11};
      this.num_to_month = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
      var day = parseInt(dateString.substring(0,2).replace(/^0*/,""));
      var month = this.month_to_num[dateString.substring(2,5)];
      var year = parseInt(dateString.substring(5,9));
      this._date = new Date(year, month, day);
};
TestDate_v1.prototype.getString = function() {
      var s = padZeroFirst(this._date.getDate()) + 
	      this.num_to_month[this._date.getMonth()] + 
              this._date.getFullYear();
      return s;
};
TestDate_v1.prototype.date = function(date) {
      if (date != undefined)
              this._date = date;
      else
              return this._date;
};
TestDate_v1.prototype.addTime = function(milliseconds) {
      this._date = new Date(this._date.valueOf() + milliseconds);
};

var TestDate_v2 = function(dateString) {
      // format:  2012-01-07[...]

      var parse = function(startix, endix) {
          return parseInt(dateString.substring(startix, endix).replace(/^0*/,""));
      };
      var year   = parse(0, 4);
      var month  = parse(5, 7) - 1;
      var day    = parse(8, 10);
      this._date = new Date(year, month, day);
};
TestDate_v2.prototype.getString = function() {
      var s = this._date.getFullYear() + "-" + 
              padZeroFirst(this._date.getMonth()+1) + "-" +
              padZeroFirst(this._date.getDate());
      return s;
};
TestDate_v2.prototype.date = function(date) {
      if (date != undefined)
              this._date = date;
      else
              return this._date;
};
TestDate_v2.prototype.addTime = function(milliseconds) {
      this._date = new Date(this._date.valueOf() + milliseconds);
};


var createTestDate = function(dateString) {
      // version 1 format:  07Jan2012,
      //                    07Jan2012.94                 
      // version 2 format:  2012-01-07_11-48-47,
      //                    2012-01-07_1148

      
      if (dateString.search(/^[0-9]{2}[a-zA-Z]{3}[0-9]{4}/) == 0) {
          return new TestDate_v1(dateString);

      }
      else if (dateString.search(/^[0-9]{4}-[0-9]{2}-[0-9]{2}/) == 0) {
          return new TestDate_v2(dateString);
      }
      else
          alert("Could not parse date string " + dateString);
};

var setupTestDate = function() {
      var testDate = null;
      var params = window.location.href.split("?");
      if (params.length > 1) {
		  testDate = createTestDate(params[1]);
      } else {
		  var dummy = "2000-01-01"; 
          testDate = createTestDate(dummy);
		  testDate.date( new Date() );
      }

      return testDate;        
};

var setup = function()
{
    var root = node();
    
    $(document.body).css('font-family','arial');
    $(document.body).append(root);	
    
    var testDate = setupTestDate();
	
	var currDate = createTestDate("2000-01-01");
	var currDateLegacy = createTestDate("01Jan2000");
	currDate.date( testDate.date() );
	currDateLegacy.date( testDate.date() );
    
	// Some test pages have both new and old date format
	// and must show both.
    var addLegacy = true;
	
    var dayInMilliseconds = 1000*60*60*24;
	
    var scrollDetect = function()
    {	
        var height = $(window).height();
        var scrollTop = $(window).scrollTop();
        var docHeight = $(document).height();
        var spaceForMoreComments = docHeight < height+scrollTop+10;
		
		if (spaceForMoreComments)
		{	
			// Layout and container
			var layout = $("<table/>").append($("<tr><td/></tr>"));
			var subroot = node().addClass('rounded');
			subroot.hover(
				function(){ $(this).css('background-color','#FFFFAA'); },
				function(){ $(this).css('background-color',''); 
			});
			root.append(layout);
			layout.find("td").append(subroot);

			var result = loadSummary(currDate);
			var result2 = loadSummary(currDateLegacy);
			var dateStrings = result.dateStrings.concat(result2.dateStrings);
			var entries = result.entries.concat(result2.entries);
			
			if (dateStrings.length == 0)
				dateStrings.push( currDate.getString() );
			
			appendSummary(subroot, dateStrings, entries);
			
			currDate.addTime(-dayInMilliseconds);
			if (addLegacy)
				currDateLegacy.addTime(-dayInMilliseconds);
		}
		setTimeout(scrollDetect, 500);
    };
    scrollDetect();	
};



$(document).ready(setup);
