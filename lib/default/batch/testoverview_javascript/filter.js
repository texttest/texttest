var Colors =
{
    OK : '#CEEFBD',                  // green
    FAILED : '#FF3118',              // ref
    KNOWN_BUG : '#FF9900',           // orange
    PERF_DIFF : '#FFC6A5',           // light brown
    MEM_DIFF : '#FF99CC',            // pink
    NA : '#DDDDDD',                  // gray
    KILLED: '#8B1A1A',               // dark red
	
    TEST_ROW_HEADER : '#FFFFCC'      // yellow
};

// A test result category.
// - Containts its color and view state
var Category = function(color)
{
    this.color = color;
    this.isVisible = true;
};
// Test if a 'test result' is of this category
Category.prototype.appliesTo = function(testElem)
{
    return testElem.bgColor.toUpperCase() == this.color;
};
Category.prototype.toggle = function()
{
    this.isVisible = !this.isVisible;
};

// Represent a row with test results
// - Contains reference to 'tr' object and last 'td' object (todays result)
var TestRow = function(trElem)
{
    var tdList = trElem.getElementsByTagName('td');
    this.lastCol = tdList[tdList.length-1];
    this.row = trElem;
};

var isTestRow = function(trElem)
{
    var tdList = trElem.getElementsByTagName('td');
    return (tdList.length > 0) 
           && tdList[0].bgColor.toUpperCase() == Colors.TEST_ROW_HEADER;
}	

// The 'manager' class
var Filter = function(bodyElem)
{
    var rowList = bodyElem.getElementsByTagName('tr');
    this.testRows = [];
    for (var i = 0; i < rowList.length; ++i)
	if (isTestRow(rowList[i]))
	    this.testRows.push(new TestRow(rowList[i]));
	
    this.categories = [];
    this.categories.push(new Category(Colors.OK));
    this.categories.push(new Category(Colors.FAILED));
    this.categories.push(new Category(Colors.PERF_DIFF));
    this.categories.push(new Category(Colors.MEM_DIFF));
    this.categories.push(new Category(Colors.KILLED));
    this.categories.push(new Category(Colors.KNOWN_BUG));
    this.categories.push(new Category(Colors.NA));
};

// Hide/Show a single row
Filter.prototype.setRowVisibility = function(testRow)
{
    var visible = true;
    for (var i = 0; i < this.categories.length; ++i)
    {
	var cat = this.categories[i];
	if (cat.appliesTo(testRow.lastCol))
	{
	    visible = cat.isVisible;
	    break;
	}
    }
    testRow.row.style.display = visible ? "" : "None";
};

// Apply the filter (hide/show rows)
Filter.prototype.apply = function()
{
    for (var i = 0; i < this.testRows.length; i++)
	this.setRowVisibility(this.testRows[i]);
};

// Create html and behavior of a category toggler
var createCategoryToggler = function(category, callback, id)
{
    var toggler = $('<div id=color' + id + '></div>');
    toggler.css({
	    'float': 'left',
	    'background-color': category.color,
	    'width': '80px',
	    'height': category.isVisible ? '100%' : '30%',
	    'margin-left': '15px'
	    });
    toggler.click(function() {		
	    category.toggle();
	    $(this).animate({height: category.isVisible?'100%':'30%'}, 
                            250, callback);
	    });
    return toggler;
};

// Initialize
var init = function()
{
    // Create html and behavior of toolbar
    // containing category togglers
    var toolbarContent = $("<div id=colorbar></div>");
    toolbarContent.css({
	    'top': '0px',
	    'left': '0px',
	    'right': '1px',
	    'height': '30px',
            'position': 'absolute',
	    'padding': '10px',
	    'background-color': '#222222',
            'opacity': '0.1'
	    });
    toolbarContent.hover(function() { $(this).stop().fadeTo('fast',0.9); }, 
			 function() { $(this).stop().fadeTo('fast',0.1); });
		
    // The filter instance
    var filter = new Filter(document.body);

    // Populate toolbar with category togglers
    for (var i = 0; i < filter.categories.length; ++i)
    {
	var cat = filter.categories[i];
	toolbarContent.append(
	    createCategoryToggler(cat, function() { filter.apply(); }, i+1));
    }

    // Insert toolbar
    $(document.body).append(toolbarContent);

    // Make sure the toolbar sits on top of page when scrolling
    $(window).scroll(function(){
	    toolbarContent.hide();
	    toolbarContent.css('top', $(this).scrollTop() + 'px');
	    toolbarContent.fadeIn('fast');
	});
};

// Run initialization function when document is loaded
$(document).ready(init);

