###IMPORTS###
import utils, basemap
import h5py
import numpy as np
import tkinter as tk
import sys,os,time,copy,fnmatch
import matplotlib as mpl
mpl.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.widgets import Cursor
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from scipy.interpolate import CubicSpline


class imPick(tk.Frame):
    # imPick is a class to pick horizons from a radar image
    def __init__(self, parent, *args, **kwargs):
        tk.Frame.__init__(self, parent, *args, **kwargs)
        self.parent = parent

        # set up frames
        infoFrame = tk.Frame(self.parent)
        infoFrame.pack(side="top",fill="both")
        toolbarFrame = tk.Frame(infoFrame)
        toolbarFrame.pack(side="bottom",fill="both")
        self.dataFrame = tk.Frame(self.parent)
        self.dataFrame.pack(side="bottom", fill="both", expand=1)

        self.im_status = tk.StringVar()
        # add radio buttons for toggling between radargram and clutter-sim
        radarRadio = tk.Radiobutton(infoFrame, text="radargram", variable=self.im_status, value="data",command=self.show_data)
        radarRadio.pack(side="left")
        clutterRadio = tk.Radiobutton(infoFrame,text="cluttergram", variable=self.im_status, value="clut",command=self.show_clut)
        clutterRadio.pack(side="left")
        tk.ttk.Separator(infoFrame,orient="vertical").pack(side="left", fill="both", padx=10, pady=4)

        # add radio buttons for toggling pick visibility
        self.pick_vis = tk.BooleanVar()
        tk.Label(infoFrame, text="pick visibility: ").pack(side="left")
        tk.Radiobutton(infoFrame,text="on", variable=self.pick_vis, value=True, command=self.show_picks).pack(side="left")
        tk.Radiobutton(infoFrame,text="off", variable=self.pick_vis, value=False, command=self.hide_picks).pack(side="left")

        tk.Button(infoFrame, text="edit", command=self.edit_pkLayer).pack(side="right")
        tk.Button(infoFrame, text="delete", command=self.delete_pkLayer).pack(side="right")

        self.layerVar = tk.IntVar()
        self.layers=[None]
        self.layerMenu = tk.OptionMenu(infoFrame, self.layerVar, *self.layers)
        self.layerMenu.pack(side="right",pady=0)
        tk.Label(infoFrame,text="subsurface pick segment: ").pack(side="right")
        # self.layerMenu["highlightthickness"]=0

        self.pickLabel = tk.Label(toolbarFrame, font= "Verdana 10")#, text="subsurface pick segment:\t0", fg="#d9d9d9")
        self.pickLabel.pack(side="right")
        tk.Label(toolbarFrame, text="\t").pack(side="right")

        self.fig = mpl.figure.Figure()
        self.fig.patch.set_facecolor("#d9d9d9")
        self.dataCanvas = FigureCanvasTkAgg(self.fig, self.parent)
        # self.dataCanvas.get_tk_widget().pack(in_=dataFrame, side="bottom", fill="both", expand=1)
        # add toolbar to plot
        self.toolbar = NavigationToolbar2Tk(self.dataCanvas, toolbarFrame)
        self.toolbar.update()
        self.click = self.fig.canvas.mpl_connect("button_press_event", self.onpress)
        self.unclick = self.fig.canvas.mpl_connect("button_release_event", self.onrelease)

        # add axes for colormap sliders and reset button - leave invisible until data loaded
        self.ax_cmax = self.fig.add_axes([0.95, 0.55, 0.01, 0.30])
        self.ax_cmax.set_visible(False)
        self.ax_cmin  = self.fig.add_axes([0.95, 0.18, 0.01, 0.30])
        self.ax_cmin.set_visible(False)
        self.reset_ax = self.fig.add_axes([0.935, 0.11, 0.04, 0.03])
        self.reset_ax.set_visible(False)
        self.ax = self.fig.add_subplot(111)

        # initiate a twin axis that shows twtt
        self.secaxy0 = self.ax.twinx()
        self.secaxy0.yaxis.set_ticks_position("left")
        self.secaxy0.yaxis.set_label_position("left")
        self.secaxy0.spines["left"].set_position(("outward", 52))
        self.secaxy0.set_ylabel("two-way travel time [microsec.]")

        # initiate a twin axis that shares the same x-axis and shows approximate depth
        self.secaxy1 = self.ax.twinx()
        self.secaxy1.yaxis.set_ticks_position("right")
        self.secaxy1.yaxis.set_label_position("right")

        # initiate a twin axis that shows along-track distance
        self.secaxx = self.ax.twiny()
        self.secaxx.xaxis.set_ticks_position("bottom")
        self.secaxx.xaxis.set_label_position("bottom")
        self.secaxx.spines["bottom"].set_position(("outward", 42))
        self.secaxx.set_xlabel("along-track distance [km]")

        # set zorder of secondary axes to be behind main axis (self.ax)
        self.secaxx.set_zorder(-100)
        self.secaxy0.set_zorder(-100)
        self.secaxy1.set_zorder(-100)

        # self.cursor = Cursor(self.ax, useblit=False, horizOn=True, vertOn=True, color="r", lw="0.5")

        self.ax.set_visible(False)

        # connect xlim_change with event to update image background for blitting
        self.draw_cid = self.fig.canvas.mpl_connect("draw_event", self.update_bg)

        # create colormap sliders and reset button - initialize for data image
        self.s_cmin = mpl.widgets.Slider(self.ax_cmin, "min", 0, 1, orientation="vertical")
        self.s_cmax = mpl.widgets.Slider(self.ax_cmax, "max", 0, 1, orientation="vertical")
        self.cmap_reset_button = mpl.widgets.Button(self.reset_ax, "reset", color="lightgoldenrodyellow")
        self.cmap_reset_button.on_clicked(self.cmap_reset)

        
    # set_vars is a method to set imPick variables
    def set_vars(self):
        self.data_imSwitch_flag = ""
        self.clut_imSwitch_flag = ""
        self.f_loadName = ""
        self.f_saveName = ""
        self.dtype = "amp"
        self.basemap = None
        self.pick_surf = None
        self.pick_dict = {}
        self.pick_dict_opt = {}
        self.pick_idx = None
        self.pick_state = False
        self.pick_segment = 0
        self.data_cmin = None
        self.data_cmax = None
        self.clut_cmin = None
        self.clut_cmax = None
        # empty fields for picks
        self.xln_old = np.array(())
        self.yln_old = np.array(())
        self.xln = []
        self.yln = []
        self.xln_surf = []
        self.yln_surf = []
        self.surf = None
        self.pick = None
        self.saved_pick = None
        self.surf_pick = None
        self.surf_pickFlag = False
        self.edit_flag = False
        self.edit_segmentNum = 0
        self.im_status.set("data")
        self.pick_vis.set(True)
        self.pickLabel.config(fg="#d9d9d9")


    # load calls ingest() on the data file and sets the datacanvas
    def load(self, f_loadName, data, eps):
        self.f_loadName = f_loadName
        
        # receive the data
        self.data = data

        self.ax.set_title(os.path.splitext(self.f_loadName.split("/")[-1])[0])
        # set scalebar axes now that data displayed
        self.ax.set_visible(True)
        self.ax_cmax.set_visible(True)
        self.ax_cmin.set_visible(True)
        self.reset_ax.set_visible(True)
        
        # set figure title
        self.ax.set_title(os.path.splitext(self.f_loadName.split("/")[-1])[0])
        self.ax.set(xlabel = "trace", ylabel = "sample")

        # calculate power of data
        Pow_data = np.power(self.data["amp"],2)
        # place data in dB for visualization
        self.dB_data = np.log10(Pow_data)

        # initialize arrays to hold saved picks
        self.xln_old = np.repeat(np.nan, self.data["num_trace"])
        self.yln_old = np.repeat(np.nan, self.data["num_trace"])

        # get clutter data in dB for visualization
        # check if clutter data exists
        if np.any(self.data["clutter"]):
            # check if clutter data is stored in linear space or log space - lin space should have values less than 1
            # if in lin space, convert to dB
            if (np.nanmax(np.abs(self.data["clutter"])) < 1) or ("2012" in self.f_loadName):
                Pow_clut = np.power(self.data["clutter"],2)
                Pow_clut[np.where(Pow_clut == 0)] = np.NaN      # avoid -inf values in dB data
                self.dB_clut = np.log10(Pow_clut)
            # if in log space, leave as is
            else:
                self.dB_clut = self.data["clutter"]
            # # replace any negative infinity clutter values with nan
            # try:
            #     self.dB_clut[np.where(self.dB_clut == -np.inf)] = np.NaN
            # except:
            #     pass
        # if no clutter data, use empty array
        else:
            self.dB_clut = self.data["clutter"]
            
        # cut off data at 10th percentile to avoid extreme outliers - round down
        self.mindB_data = np.floor(np.nanpercentile(self.dB_data,10))
        self.mindB_clut = np.floor(np.nanpercentile(self.dB_clut,10))
        
        self.maxdB_data = np.nanmax(self.dB_data)
        self.maxdB_clut = np.nanmax(self.dB_clut)
        if ("2012" in self.f_loadName):
            self.maxdB_clut = np.floor(np.nanpercentile(self.dB_clut,90))

        # print(self.mindB_data,self.maxdB_data)
        # print(self.mindB_clut,self.maxdB_clut)

        self.dataCanvas.get_tk_widget().pack(in_=self.dataFrame, side="bottom", fill="both", expand=1) 

        # display image data for radargram and clutter sim
        self.im_data  = self.ax.imshow(self.dB_data, cmap="Greys_r", aspect="auto", extent=[self.data["trace"][0], 
                        self.data["trace"][-1], self.data["sample"][-1], self.data["sample"][0]])
        self.im_clut  = self.ax.imshow(self.dB_clut, cmap="Greys_r", aspect="auto", extent=[self.data["trace"][0], 
                        self.data["trace"][-1], self.data["sample"][-1], self.data["sample"][0]])

        # update colormaps
        self.im_data.set_clim([self.mindB_data, self.maxdB_data])
        self.im_clut.set_clim([self.mindB_clut, self.maxdB_clut])

        # set slider bounds
        self.s_cmin.valmin = self.mindB_data - 10
        self.s_cmin.valmax = self.mindB_data + 10
        self.s_cmin.valinit = self.mindB_data
        self.s_cmax.valmin = self.maxdB_data - 10
        self.s_cmax.valmax = self.maxdB_data + 10
        self.s_cmax.valinit = self.maxdB_data

        self.update_slider()

        # set clutter sim visibility to false
        self.im_clut.set_visible(False)

        # plot lidar surface
        self.surf, = self.ax.plot(self.data["trace"], self.data["surf_idx"],"c")

        self.pick, = self.ax.plot([],[],"rx")                                       # empty line for current pick segment
        self.saved_pick, = self.ax.plot([],[],"g")                                  # empty line for saved pick
        self.surf_pick, = self.ax.plot([],[],"mx")                                  # empty line for surface pick segment

        # plot any imported picks if desired
        if (self.data["num_importedPicks"] > 0) and (tk.messagebox.askyesno("plot picks","would you like to display previous picks?") == True):
            for _i in range(self.data["num_importedPicks"]):
                self.ax.plot(utils.twtt2sample(self.data["pick"]["twtt_subsurf" + str(_i)], self.data["dt"]), "b")

        # set axes extents
        self.set_axes(eps)

        # update the canvas
        self.dataCanvas._tkcanvas.pack()
        self.dataCanvas.draw()

        # save background
        self.update_bg()

        # self.cursor = Cursor(self.ax, useblit=False, horizOn=True, vertOn=True, color="r", lw="0.5")

        # update toolbar to save axes extents
        self.toolbar.update()


    # get_pickState is a method to return the current picking state
    def get_pickState(self):
        return self.pick_state

    def get_pickSurf(self):
        return self.pick_surf


    # set_pickState is a method to generate a new pick dictionary layer and plot the data
    def set_pickState(self, state, surf = None):
        self.pick_state = state
        self.pick_surf = surf
        if self.pick_surf == "subsurface":
            if self.pick_state == True:
                # if a layer was already being picked, advance the pick segment count to begin new layer
                if len(self.xln) >= 2:
                    self.pick_segment += 1
                # if current subsurface pick layer has only one pick, remove
                else:
                    self.clear_last()
                self.pickLabel.config(text="subsurface pick segment " + str(self.pick_segment) + ":\t active", fg="red")
                # initialize pick index and twtt dictionaries for current picking layer
                self.pick_dict["segment_" + str(self.pick_segment)] = np.ones(self.data["num_trace"])*-1

            elif self.pick_state == False and self.edit_flag == False:
                if len(self.xln) >=  2:
                    self.pick_segment += 1
                    self.pickLabel.config(text="subsurface pick segment " + str(self.pick_segment - 1) + ":\t inactive", fg="black")
                # if surface pick layer has only one pick, remove
                else:
                    self.clear_last()
                    self.pickLabel.config(text="subsurface pick segment " + str(self.pick_segment) + ":\t inactive", fg="black")

            else:
                self.pickLabel.config(text="subsurface pick segment " + str(self.pick_segment) + ":\t inactive", fg="black")

        elif self.pick_surf == "surface":
            if self.pick_state == True:
                self.pickLabel.config(text="surface pick segment:\t active", fg="red")
            elif self.pick_state == False:
                self.pickLabel.config(text="surface pick segment:\t inactive", fg="black")


    # addseg is a method to for user to generate picks
    def addseg(self, event):
        if self.f_loadName:
            # store pick trace idx as integer
            self.pick_trace = int(event.xdata)
            # store pick sample idx as integer
            pick_sample = int(event.ydata)

            # check if picking state is a go
            if self.pick_state == True:
                # restrict subsurface picks to fall below surface
                if (self.pick_surf == "subsurface") and ((pick_sample > self.data["surf_idx"][self.pick_trace]) or (np.isnan(self.data["surf_idx"][self.pick_trace]))):
                # make sure pick falls after previous pick
                    if (len(self.xln) >= 1) and (self.pick_trace <= self.xln[-1]):
                        pass
                    else:
                        self.xln.append(self.pick_trace)
                        self.yln.append(pick_sample)
                        # set self.pick data to plot pick on image
                        self.pick.set_data(self.xln, self.yln)
                elif self.pick_surf == "surface":
                    if (len(self.xln_surf) >= 1) and (self.pick_trace <= self.xln_surf[-1]):
                        pass
                    else:
                        self.xln_surf.append(self.pick_trace)
                        self.yln_surf.append(pick_sample)
                        # set self.surf_pick data to plot pick on image
                        self.surf_pick.set_data(self.xln_surf, self.yln_surf)
                        self.surf_pickFlag = True
                self.blit()

            # plot pick location to basemap
            if self.basemap and self.basemap.get_state() == 1:
                self.basemap.plot_idx(self.pick_trace)


    # pick_interp is a method for cubic spline interpolation of twtt between pick locations
    def pick_interp(self,surf = None):
        # if there are at least two picked points, interpolate
        try:
            if surf == "subsurface":
                if len(self.xln) >= 2:                   
                    # cubic spline between picks
                    cs = CubicSpline(self.xln,self.yln)
                    # generate array between first and last pick indices on current layer
                    picked_traces = np.arange(self.xln[0],self.xln[-1] + 1)
                    # add cubic spline output interpolation to pick dictionary - force output to integer for index of pick
                    if self.edit_flag == True:
                        self.pick_dict["segment_" + str(self.layerVar.get())][picked_traces] = cs([picked_traces]).astype(int)
                        # add pick interpolation to saved pick array
                        self.xln_old[picked_traces] = picked_traces
                        self.yln_old[picked_traces] = self.pick_dict["segment_" + str(self.layerVar.get())][picked_traces]
                        self.edit_flag = False
                    else:
                        self.pick_dict["segment_" + str(self.pick_segment - 1)][picked_traces] = cs([picked_traces]).astype(int)
                        # add pick interpolation to saved pick array
                        self.xln_old[picked_traces] = picked_traces
                        self.yln_old[picked_traces] = self.pick_dict["segment_" + str(self.pick_segment - 1)][picked_traces]                

            elif surf == "surface":
                if len(self.xln_surf) >= 2:
                    # cubic spline between surface picks
                    cs = CubicSpline(self.xln_surf,self.yln_surf)
                    # generate array between first and last pick indices on current layer
                    picked_traces = np.arange(self.xln_surf[0],self.pick_trace + 1)
                    # input cubic spline output surface twtt array - force output to integer for index of pick
                    self.data["surf_idx"][picked_traces] = cs([picked_traces]).astype(int)
                    # update twtt_surf
                    self.data["twtt_surf"][picked_traces] = cs([picked_traces]).astype(int)*self.data["dt"]

        except Exception as err:
            print("Pick interp error: " + str(err))


    # plot_picks is a method to remove current pick list and add saved picks to plot
    def plot_picks(self, surf = None):
        if surf == "subsurface":
            # remove saved picks
            del self.xln[:]
            del self.yln[:]
            self.pick.set_data(self.xln, self.yln)
            # self.saved_pick.set_offsets(np.c_[self.xln_old,self.yln_old])
            self.saved_pick.set_data(self.xln_old,self.yln_old)
        elif surf == "surface":
            del self.xln_surf[:]
            del self.yln_surf[:]
            self.surf_pick.set_data(self.xln_surf, self.yln_surf)
            self.surf.set_data(self.data["trace"], self.data["surf_idx"])
            

    def clear_picks(self, surf = None):
        # clear all picks
        if surf == "subsurface":
            if len(self.xln) + np.count_nonzero(~np.isnan(self.xln_old)) > 0:
                # set picking state to false
                self.set_pickState(False,surf="subsurface")
                # delete pick lists
                self.yln_old[:] = np.nan
                self.xln_old[:] = np.nan
                # clear pick dictionary
                self.pick_dict.clear()
                self.pick_dict_opt.clear()
                # reset pick segment increment to 0
                self.pick_segment = 0
                self.pickLabel.config(fg="#d9d9d9")
                self.layerVar.set(self.pick_segment)
        elif surf == "surface":
            self.data["surf_idx"].fill(np.nan)
            self.surf_pickFlag = False


    def clear_last(self):
        # clear last pick
        if self.pick_state == True:
            if self.pick_surf == "subsurface" and len(self.xln) >= 1:
                del self.xln[-1:]
                del self.yln[-1:]
                self.pick_trace = self.xln[-1]
                # reset self.pick, then blit
                self.pick.set_data(self.xln, self.yln)
                self.blit()

            if self.pick_surf == "surface" and len(self.xln_surf) >= 1:
                del self.xln_surf[-1:]
                del self.yln_surf[-1:]
                self.pick_trace = self.xln[-1]
                # reset self.pick, then blit
                self.surf_pick.set_data(self.xln_surf, self.yln_surf)
                self.blit()
                if len(self.xln_surf) == 0:
                    self.surf_pickFlag = False

    def edit_pkLayer(self):
        if (len(self.pick_dict) > 0) and (self.edit_flag == False) and (not ((self.pick_state == True) and (self.pick_surf == "subsurface") and (self.layerVar.get() == self.pick_segment))) and (tk.messagebox.askokcancel("warning", "edit pick segment " + str(self.layerVar.get()) + "?", icon = "warning") == True):
            # if another subsurface pick segment is active, end segment
            if (self.pick_state == True) and (self.pick_surf == "subsurface") and (self.layerVar.get() != self.pick_segment):
                self.set_pickState(False, surf="subsurface")
                self.pick_interp(surf = "subsurface")
                self.plot_picks(surf = "subsurface")
                self.update_option_menu()
            self.edit_flag = True
            self.edit_segmentNum = self.layerVar.get()
            self.pick_state = True
            self.pick_surf = "subsurface"
            # find indices of picked traces
            picks_idx = np.where(self.pick_dict["segment_" + str(self.layerVar.get())] != -1)[0]
            # return picked traces to xln list
            self.xln = picks_idx.tolist()
            # return picked samples to yln list
            self.yln = self.pick_dict["segment_" + str(self.layerVar.get())][picks_idx].tolist()
            # clear saved picks
            self.xln_old[picks_idx] = np.nan
            self.yln_old[picks_idx] = np.nan
            self.pick_dict["segment_" + str(self.layerVar.get())][picks_idx] = -1
            # reset plotted lines
            self.pick.set_data(self.xln, self.yln)
            self.saved_pick.set_data(self.xln_old,self.yln_old)
            # update pick label
            self.pickLabel.config(text="subsurface pick segment " + str(self.layerVar.get()) + ":\t active", fg="red")
            self.blit()


    def delete_pkLayer(self):
        # delete selected pick segment
        if (len(self.pick_dict) > 0) and (tk.messagebox.askokcancel("warning", "delete pick segment " + str(self.layerVar.get()) + "?", icon = "warning") == True):
            # if picking active and only one segment exists, clear all picks
            if (self.pick_state == True) and (len(self.pick_dict) == 1):
                self.clear_picks(surf = "subsurface")
                self.plot_picks(surf = "subsurface")

            else:
                if self.edit_flag == True and self.edit_segmentNum == self.layerVar.get():
                    # clear active pick lists
                    del self.xln[:]
                    del self.yln[:]
                    self.pick.set_data(self.xln, self.yln)
                    self.edit_flag = False
                    self.set_pickState(False, "subsurface")

                else:
                    # get picked traces for layer
                    picks_idx = np.where(self.pick_dict["segment_" + str(self.layerVar.get())] != -1)[0]
                    # remove picks from plot list
                    self.xln_old[picks_idx] = np.nan
                    self.yln_old[picks_idx] = np.nan
                    self.saved_pick.set_data(self.xln_old,self.yln_old)

                

                # delete pick dict layer
                del self.pick_dict["segment_" + str(self.layerVar.get())]
                
                if self.pick_segment >=1:
                    self.pick_segment -= 1 

                if self.edit_flag == True:

                    print(self.pick_segment)
                    self.pick_segment -= 1

                # reorder pick layers
                if self.layerVar.get() != len(self.pick_dict):
                    for _i in range(self.layerVar.get(), len(self.pick_dict)):
                        self.pick_dict["segment_" + str(_i)] = np.copy(self.pick_dict["segment_" + str(_i + 1)])
                    del self.pick_dict["segment_" + str(_i + 1)]

                if self.pick_state == True:
                    if self.edit_flag == True:
                        self.pickLabel.config(text="subsurface pick segment " + str(self.edit_segmentNum) + ":\t active", fg="red")
                    else:
                        self.pickLabel.config(text="subsurface pick segment " + str(self.pick_segment) + ":\t active", fg="red")

                elif self.pick_state == False:
                    if self.pick_segment >= 1:
                        self.pickLabel.config(text="subsurface pick segment " + str(self.pick_segment - 1) + ":\t inactive", fg="black")   
                    else:
                        self.pickLabel.config(text="subsurface pick segment " + str(self.pick_segment) + ":\t inactive", fg="#d9d9d9")
                self.layerVar.set(0)
            self.update_option_menu()
            self.update_bg()


    def show_data(self):
        # toggle to radar data
        # get clutter colormap slider values for reviewing
        self.clut_cmin = self.s_cmin.val
        self.clut_cmax = self.s_cmax.val
        # set colorbar initial values to previous values
        self.s_cmin.valinit = self.data_cmin
        self.s_cmax.valinit = self.data_cmax
        # set colorbar bounds
        self.s_cmin.valmin = self.mindB_data - 10
        self.s_cmin.valmax = self.mindB_data + 10
        self.s_cmax.valmin = self.maxdB_data - 10
        self.s_cmax.valmax = self.maxdB_data + 10
        self.update_slider()
        # reverse visilibilty
        self.im_clut.set_visible(False)
        self.im_data.set_visible(True)
        # redraw canvas
        self.fig.canvas.draw()
        self.im_status.set("data")


    def show_clut(self):
        # toggle to clutter sim viewing
        # get radar data colormap slider values for reviewing
        self.data_cmin = self.s_cmin.val
        self.data_cmax = self.s_cmax.val

        if not self.clut_imSwitch_flag:
            # if this is the first time viewing the clutter sim, set colorbar limits to initial values
            self.s_cmin.valinit = self.mindB_clut
            self.s_cmax.valinit = self.maxdB_clut
        else: 
            # if clutter has been shown before revert to previous colorbar values
            self.im_clut.set_clim([self.clut_cmin, self.clut_cmax])
            self.s_cmin.valinit = self.clut_cmin
            self.s_cmax.valinit = self.clut_cmax

        self.s_cmin.valmin = self.mindB_clut - 10
        self.s_cmin.valmax = self.mindB_clut + 10            
        self.s_cmax.valmin = self.maxdB_clut - 10
        self.s_cmax.valmax = self.maxdB_clut + 10
        self.update_slider()
        # reverse visilibilty
        self.im_data.set_visible(False)
        self.im_clut.set_visible(True)
        # set flag to indicate that clutter has been viewed for resetting colorbar limits
        self.clut_imSwitch_flag = True    
        # redraw canvas
        self.fig.canvas.draw()
        self.im_status.set("clut")


    # pick_vis is a method to toggle the visibility of picks
    def show_picks(self):
        self.show_artists()
        self.safe_draw()
        self.fig.canvas.blit(self.ax.bbox)


    def hide_picks(self):
        self.hide_artists()
        self.safe_draw()
        self.fig.canvas.blit(self.ax.bbox)


    # update the pick layer menu based on how many layers exist
    def update_option_menu(self):
            menu = self.layerMenu["menu"]
            menu.delete(0, "end")
            for _i in range(self.pick_segment):
                menu.add_command(label=_i,
                    command=tk._setit(self.layerVar,_i))


    def update_slider(self):
        self.ax_cmax.clear()
        self.ax_cmin.clear()
        self.s_cmin.__init__(self.ax_cmin, "min", valmin=self.s_cmin.valmin, valmax=self.s_cmin.valmax, valinit=self.s_cmin.valinit, orientation="vertical")
        self.s_cmax.__init__(self.ax_cmax, "max", valmin=self.s_cmax.valmin, valmax=self.s_cmax.valmax, valinit=self.s_cmax.valinit, orientation="vertical")
        self.s_cmin.on_changed(self.cmap_update)
        self.s_cmax.on_changed(self.cmap_update)


    def cmap_update(self, s=None):
        # method to update image colormap based on slider values
        try:
            if self.im_data.get_visible():
                # apply slider values to visible image
                self.data_cmin = self.s_cmin.val
                self.data_cmax = self.s_cmax.val
                self.im_data.set_clim([self.data_cmin, self.data_cmax])
            else:
                self.clut_cmin = self.s_cmin.val
                self.clut_cmax = self.s_cmax.val
                self.im_clut.set_clim([self.clut_cmin, self.clut_cmax])
        except Exception as err:
            print("cmap_update error: " + str(err))


    def cmap_reset(self, event):
        # reset sliders to initial values
        if self.im_data.get_visible():
            self.s_cmin.valmin = self.mindB_data - 10
            self.s_cmin.valmax = self.mindB_data + 10
            self.s_cmin.valinit = self.mindB_data
            self.s_cmax.valmin = self.maxdB_data - 10
            self.s_cmax.valmax = self.maxdB_data + 10
            self.s_cmax.valinit = self.maxdB_data
        else:
            # if clutter is displayed, change slider bounds
            self.s_cmin.valmin = self.mindB_clut - 10
            self.s_cmin.valmax = self.mindB_clut + 10
            self.s_cmin.valinit = self.mindB_clut
            self.s_cmax.valmin = self.maxdB_clut - 10
            self.s_cmax.valmax = self.maxdB_clut + 10
            self.s_cmax.valinit = self.maxdB_clut
        self.update_slider()
        self.cmap_update()


    def safe_draw(self):
        """temporarily disconnect the draw_event callback to avoid recursion"""
        canvas = self.fig.canvas
        canvas.mpl_disconnect(self.draw_cid)
        canvas.draw()
        self.draw_cid = canvas.mpl_connect("draw_event", self.update_bg)


    def hide_artists(self):
        for _i in self.ax.lines:
            _i.set_visible(False)
        # if self.surf:
        #     self.surf.set_visible(False)
        # if self.surf_pick:
        #     self.surf_pick.set_visible(False)
        # if self.pick:
        #     self.pick.set_visible(False)
        # if self.saved_pick:
        #     self.saved_pick.set_visible(False)


    def show_artists(self):
        for _i in self.ax.lines:
            _i.set_visible(True)
        # if self.surf:
        #     self.surf.set_visible(True)
        # if self.surf_pick:
        #     self.surf_pick.set_visible(True)
        # if self.pick:
        #     self.pick.set_visible(True)
        # if self.saved_pick:
        #     self.saved_pick.set_visible(True)

            
    def update_bg(self, event=None):
        """
        when the figure is resized, hide picks, draw everything,
        and update the background.
        """
        self.hide_artists()
        self.safe_draw()
        self.axbg = self.dataCanvas.copy_from_bbox(self.ax.bbox)
        self.show_artists()
        self.blit()


    def blit(self):
        """
        update the figure, without needing to redraw the
        "axbg" artists.
        """
        self.fig.canvas.restore_region(self.axbg)
        # if self.pick:
        #     self.ax.draw_artist(self.pick)
        # if self.saved_pick:
        #     self.ax.draw_artist(self.saved_pick)
        # if self.surf_pick:
        #     self.ax.draw_artist(self.surf_pick)
        # if self.surf:
        #     self.ax.draw_artist(self.surf)
        for _i in self.ax.lines:
            self.ax.draw_artist(_i)
        self.fig.canvas.blit(self.ax.bbox)


    # nextSave_warning is a method which checks if picks exist or if the user would like to discard existing picks before moving to the next track
    def nextSave_warning(self):
        # check if picks have been made and saved
        if ((self.get_subsurfPickFlag() == True) or (self.surf_pickFlag == True)) and (self.f_saveName == ""):
            if tk.messagebox.askyesno("Warning", "Load next track without saving picks?", icon = "warning") == True:
                return True
        else: 
            return True


    # clear_canvas is a method to clear the data canvas and figures to reset app
    def clear_canvas(self):
        # clearing individual axis objects seems to keep a history of these objects and causes axis limit issues when opening new track
        self.ax.cla()
        # for _i in self.ax.lines:
        #     self.ax.lines.remove(_i)
        # for _i in self.ax.images:
        #     self.ax.images.remove(_i)
        # for _i in self.ax.collections:
        #     self.ax.collections.remove(_i)


    # get_subsurfPickFlag is a method which returns true if manual subsurface picks exist, and false otherwise   
    def get_subsurfPickFlag(self):
        if len(self.xln) + np.count_nonzero(~np.isnan(self.xln_old)) > 0:
            return True
        else:
            return False


    # get_surfPickFlag is a method which returns true if manual surface picks exist, and false otherwise
    def get_surfPickFlag(self):
        return self.surf_pickFlag


    # get_numPkLyrs is a method to return the number of picking layers which exist
    def get_numPkLyrs(self):
        return len(self.pick_dict)


    # get_pickDict is a method to return the pick dictionary
    def get_pickDict(self):
        return self.pick_dict

    
    # set_picDict is a method to update the pick dictionary based on wvPick pick updates
    def set_pickDict(self, in_dict):
        if self.pick_dict:
            self.pick_dict_opt = in_dict
            # delete yln_old list to reset with new dictionary values for replotting
            del self.yln_old[:]
            for _i in range(len(self.pick_dict_opt)):
                picked_traces = np.where(self.pick_dict_opt["segment_" + str(_i)] != -1.)[0]
                self.yln_old.extend(self.pick_dict_opt["segment_" + str(self.pick_segment - 1)][picked_traces])


    def set_axes(self, eps):
        self.ax.set_xlim((self.data["trace"][0], self.data["trace"][-1]))
        self.ax.set_ylim((self.data["sample"][-1],self.data["sample"][0]))

        # xmin, xmax = self.ax.get_ylim()
        # ymin, ymax = self.ax.get_ylim()
        # update twtt and depth (subradar dist.)
        self.secaxy0.set_ylim(self.data["sample_time"][-1]*1e6, self.data["sample_time"][0]*1e6)
        self.secaxy1.set_ylim(utils.twtt2depth(self.data["sample_time"][-1],eps), utils.twtt2depth(self.data["sample_time"][0],eps))
        self.secaxy1.set_ylabel("approx. subradar distance [km] ($\epsilon_{}$ = {}".format("r",eps))

        # update along-track distance
        self.secaxx.set_xlim(self.data["dist"][0], self.data["dist"][-1])

        self.dataCanvas.draw()


    # get_nav method returns the nav data       
    def get_nav(self):
        return self.data["navdat"]


    # get_idx is a method that reurns the trace index of a click event on the image
    def get_idx(self):
        return self.pick_idx_x


    # set_im is a method to set which data is being displayed
    def set_im(self):
        if self.im_status.get() == "data":
            self.show_clut()

        elif self.im_status.get() =="clut":
            self.show_data()


    # get_basemap is a method to hold the basemap object passed from gui
    def get_basemap(self, basemap):
        self.basemap = basemap


    # save is a method to receive the pick save location from gui and save using utils.save
    def save(self, f_saveName, eps, figSize):
        self.f_saveName = f_saveName
        if self.pick_dict_opt:
            utils.savePick(self,f_loadName, self.f_saveName, self.data, self.pick_dict_opt, eps)
        else:
            utils.savePick(self.f_loadName, self.f_saveName, self.data, self.pick_dict, eps)
        # zoom out to full rgram extent to save pick image
        self.set_axes(eps)
        if self.im_status.get() =="clut":
            self.show_data()
        # self.update_bg()
        # self.blit()
        # temporarily turn sliders to invisible for saving image
        self.ax_cmax.set_visible(False)
        self.ax_cmin.set_visible(False)
        self.reset_ax.set_visible(False)
        w,h = self.fig.get_size_inches()    # get pre-save figure size
        self.fig.set_size_inches((float(figSize[0]),float(figSize[1])))    # set figsize to wide aspect ratio
        utils.exportIm(self.f_saveName, self.fig)
        # return figsize to intial values and make sliders visible again
        self.fig.set_size_inches((w,h))
        self.ax_cmax.set_visible(True)
        self.ax_cmin.set_visible(True)
        self.reset_ax.set_visible(True)
        self.update_bg()


    # onpress gets the time of the button_press_event
    def onpress(self,event):
        self.time_onclick = time.time()


    # onrelease calls addseg() if the time between the button press and release events
    # is below a threshold so that segments are not drawn while trying to zoom or pan
    def onrelease(self,event):
        if event.inaxes == self.ax:
            if event.button == 1 and ((time.time() - self.time_onclick) < 0.25):
                self.addseg(event)